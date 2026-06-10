#!/usr/bin/env python3
"""Stage 3 — Hybrid training loop: classical forward, quantum gradients, classical update.

Implements workflow Stage 3 of ``docs/workflows/01-qml-workflow.md``:

* :class:`HybridModel` — the Stage 1 ``MinimalTransformer`` with a VQC
  adapter head inserted into the residual stream before the output head
  (the research doc §5 "tractable today" item (ii): a small VQC head on a
  classical LM, with ``freeze_base`` available for the frozen-LM variant),
  implemented as a PennyLane QNode with ``interface="torch"`` so PyTorch
  autograd flows through the parameter-shift rule automatically.
* Quantum block restricted to <= 16 qubits and depth O(log n) with **local**
  cost observables (single-qubit PauliZ per wire), per the barren-plateau
  constraint: random deep VQCs with global costs have gradient variance
  O(2⁻ⁿ) **[Proven]** (McClean et al.), while local costs at depth O(log n)
  retain polynomially vanishing, trainable gradients **[Proven]** (Cerezo et
  al.) — research doc §3.3–3.4. Both bounds are *enforced* at config time.
* :func:`train_hybrid` supporting ``default.qubit`` (assignment default) and
  ``lightning.qubit``; when lightning runs analytic adjoint differentiation,
  a prominent note is logged that adjoint's O(1)-sweep amortization exists
  **only on classical simulators** — hardware gradient economics remain
  O(d/ε²) circuit executions (research doc §3.1 [Proven]).
* A shot-based mode (``--shots 1024``) alongside the analytic mode, so the
  measured gradient-variance gap between the two is itself a recorded result.
* A control experiment: identical architecture with the quantum block
  replaced by a classical adapter of **exactly matched** trainable middle
  parameter count. The research doc predicts an expected null result — the
  hybrid matching, not beating, the control is the anticipated outcome and
  is reported as such; no superiority claim is logged unless it exceeds the
  control by > 2σ across >= 5 seeds (workflow Stage 3 acceptance).
* Per-step wall-clock, gradient variance, and circuit-execution counts logged
  to ``qml-accelerator/benchmarks/hybrid_run_log.json``.

Loop anatomy (one step): classical forward pass through the transformer ->
quantum gradient estimation for the adapter's circuit parameters
(parameter-shift via the PennyLane+PyTorch bridge on ``default.qubit``) ->
classical AdamW weight update for *all* parameters. The QNode executes
per sample (one circuit per token hidden state), not broadcasted:
parameter-shift cannot differentiate broadcasted trainable parameters
(pennylane#4462), and real hardware executes one circuit at a time anyway,
so the per-sample loop is the more faithful reference model.

What is simulated vs. real: the QNode executes on a statevector simulator;
per the workflow ground rules, its wall-clock times validate correctness only
and are never evidence about quantum hardware speed. The hardware-honest
quantities logged here are circuit-execution *counts* (demonstrating the O(d)
parameter-shift scaling, research doc §3.1) and the analytic-vs-shot gradient
variance gap.

Dependency policy: requires torch + pennylane to train; ``--dry-run`` prints
the full execution plan (qubits, depth, parameter counts, expected circuit
executions per step, citations) with no heavy dependency installed, and the
``__main__`` entry fails gracefully with an install message otherwise.

Usage::

    python hybrid_training_loop.py --device default.qubit --steps 200
    python hybrid_training_loop.py --device lightning.qubit --steps 200
    python hybrid_training_loop.py --shots 1024 --steps 50
    python hybrid_training_loop.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Coupled Stage 1 / Stage 2 imports. The simulations directory is put on
# sys.path so this file runs both as a script and from the repo root.
# classical_transformer re-exports `torch`/`nn` (real or importable stubs),
# keeping a single source of truth for the torch-less import path.
# --------------------------------------------------------------------------
_SIM_DIR = Path(__file__).resolve().parent
if str(_SIM_DIR) not in sys.path:
    sys.path.insert(0, str(_SIM_DIR))

from classical_transformer import (  # noqa: E402
    TORCH_AVAILABLE,
    MinimalTransformer,
    ModelConfig,
    SyntheticDataset,
    make_synthetic_dataset,
    nn,
    torch,
)
from quantum_attention import (  # noqa: E402
    parameter_shift_executions,
    shots_for_precision,
)

try:  # PennyLane guarded separately: Stage 3 needs qml.qnn.TorchLayer.
    import pennylane as qml

    PENNYLANE_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    PENNYLANE_AVAILABLE = False
    qml = None  # type: ignore[assignment]

INSTALL_MESSAGE = (
    "ERROR: Stage 3 requires PyTorch and PennyLane "
    "(workflow prerequisites: torch >= 2.3, pennylane >= 0.38).\n"
    "Install with:  pip install 'torch>=2.3' 'pennylane>=0.38' "
    "'pennylane-lightning>=0.38'\n"
    "Run with --dry-run to print the execution plan without dependencies."
)

# Research doc §3.1 [Proven]; workflow Stage 3 step 3 mandates this note be
# logged prominently whenever adjoint differentiation is used.
ADJOINT_NOTE = (
    "NOTE [Proven]: adjoint differentiation's O(1)-sweep amortization exists "
    "ONLY on classical simulators — there is no hardware analogue of "
    "reverse-mode backpropagation. On hardware, gradient cost remains "
    "O(d/eps^2) circuit executions per step "
    "(research doc 01-qml-accelerator.md §3.1; workflow Stage 3 step 3)."
)

MAX_QUBITS = 16  # workflow Stage 3 step 2: quantum block restricted to <= 16


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
@dataclass
class HybridConfig:
    """Hyperparameters for the Stage 3 hybrid run.

    Validation enforces the workflow Stage 3 step 2 envelope: <= 16 qubits
    and circuit depth O(log n) (here: q_depth <= ceil(log2(n_qubits)) + 1),
    citing the barren-plateau results of research doc §3.3–3.4.

    ``batch_size``/``seq_len`` default smaller than Stage 1's because every
    token's hidden state routes through the simulator QNode; per the workflow
    ground rules the simulator cost is a correctness-validation cost, not a
    hardware measurement, so we keep it tractable.
    """

    n_qubits: int = 8
    q_depth: int = 2
    device_name: str = "default.qubit"
    shots: int | None = None  # None = analytic mode; 1024 = shot-based mode
    steps: int = 200
    batch_size: int = 8
    seq_len: int = 32
    lr: float = 3e-4
    seed: int = 42
    freeze_base: bool = False  # True = research doc §5(ii) frozen-LM variant

    def __post_init__(self) -> None:
        if self.n_qubits > MAX_QUBITS:
            raise ValueError(
                f"n_qubits={self.n_qubits} exceeds the workflow Stage 3 limit "
                f"of {MAX_QUBITS} qubits (docs/workflows/01-qml-workflow.md, "
                "Stage 3 step 2)."
            )
        max_depth = math.ceil(math.log2(self.n_qubits)) + 1
        if self.q_depth > max_depth:
            raise ValueError(
                f"q_depth={self.q_depth} violates the depth O(log n) "
                f"trainability constraint (<= {max_depth} for n_qubits="
                f"{self.n_qubits}); local costs at depth O(log n) keep "
                "gradients polynomially vanishing [Proven] — research doc "
                "§3.3–3.4 (Cerezo et al.)."
            )

    @property
    def quantum_param_count(self) -> int:
        """Trainable circuit parameters d_q: one RY per qubit per layer."""
        return self.q_depth * self.n_qubits

    @property
    def diff_method(self) -> str:
        """Differentiation method bound to the QNode.

        Shot-based mode always uses parameter-shift (the hardware-faithful
        economics). Analytic lightning.qubit uses adjoint for speed — with
        :data:`ADJOINT_NOTE` logged. Analytic default.qubit uses
        parameter-shift, per the assignment's Stage 3 specification.
        """
        if self.shots:
            return "parameter-shift"
        if self.device_name == "lightning.qubit":
            return "adjoint"
        return "parameter-shift"

    @property
    def expected_executions_per_sample(self) -> int:
        """Expected circuit executions per QNode sample in shift mode.

        1 forward evaluation + 2 shifted evaluations per trainable circuit
        parameter (parameter-shift) — the O(d) economics of research doc
        §3.1 [Proven]. The trainable parameters are the d_q circuit weights
        *plus* the n_qubits embedding angles: the upstream squeeze linear
        trains end-to-end, so gradients must also flow through the
        AngleEmbedding inputs.
        """
        return 1 + parameter_shift_executions(
            self.quantum_param_count + self.n_qubits
        )

    @property
    def expected_executions_per_step(self) -> int:
        """Expected circuit executions per training step in shift mode.

        Per-sample cost times ``batch_size * seq_len`` samples — the QNode
        executes once per token hidden state, per-sample rather than
        broadcasted (see :meth:`QuantumAdapterHead.forward`: pennylane#4462
        rules out parameter-shift over broadcasted trainable parameters,
        and per-circuit execution is the hardware-faithful model anyway).
        Recorded alongside the simulator-measured tracker count.
        """
        return (
            self.expected_executions_per_sample * self.batch_size * self.seq_len
        )


# --------------------------------------------------------------------------
# Adapters: quantum head and parameter-matched classical control
# --------------------------------------------------------------------------
class QuantumAdapterHead(nn.Module):
    """VQC adapter: Linear squeeze -> QNode (torch bridge) -> Linear expand.

    Circuit: AngleEmbedding (RY) of the squeezed features, then
    ``q_depth`` BasicEntanglerLayers (one RY per qubit per layer + CNOT
    ring), measured as one **local** ⟨Z_w⟩ per wire — local observables per
    Cerezo et al. [Proven], research doc §3.3–3.4. The QNode is wrapped in
    ``qml.qnn.TorchLayer`` with ``interface="torch"`` so ``loss.backward()``
    drives quantum gradient estimation (parameter-shift on ``default.qubit``)
    automatically — workflow Stage 3 step 1.

    Angle encoding uses n qubits for n features at O(n) depth [Proven]
    (research doc §3.1) — deliberately chosen over amplitude encoding to keep
    the adapter free of the O(2^n) state-prep wall that Stage 2's
    ``QuantumSoftmaxSampler`` accounts for.
    """

    def __init__(self, d_model: int, config: HybridConfig) -> None:
        """Build squeeze/expand linears and the device-bound TorchLayer."""
        super().__init__()
        if not (TORCH_AVAILABLE and PENNYLANE_AVAILABLE):
            raise ImportError(INSTALL_MESSAGE)
        self.config = config
        n = config.n_qubits
        self.squeeze = nn.Linear(d_model, n)
        self.expand = nn.Linear(n, d_model)
        # Device binding happens here; train_hybrid()'s device_name argument
        # must match config.device_name (asserted there).
        self.device_ref = qml.device(
            config.device_name, wires=n, shots=config.shots
        )

        @qml.qnode(self.device_ref, interface="torch", diff_method=config.diff_method)
        def qnode(inputs: Any, weights: Any) -> list[Any]:
            qml.AngleEmbedding(inputs, wires=range(n), rotation="Y")
            qml.BasicEntanglerLayers(weights, wires=range(n))
            # LOCAL cost observables (single-qubit), research doc §3.3-3.4.
            return [qml.expval(qml.PauliZ(w)) for w in range(n)]

        self.qlayer = qml.qnn.TorchLayer(
            qnode, {"weights": (config.q_depth, n)}
        )

    def middle_parameters(self) -> list["torch.Tensor"]:
        """The quantum circuit parameters (interface shared with the control)."""
        return [p for _, p in self.qlayer.named_parameters()]

    def forward(self, h: "torch.Tensor") -> "torch.Tensor":
        """Route hidden states (B, L, D) through the VQC; same output shape.

        The QNode is executed **per sample** (one circuit input at a time)
        rather than as one broadcasted (B*L, n) call. Two reasons:

        1. Correctness: PennyLane's parameter-shift transform cannot
           differentiate broadcasted tapes with respect to broadcasted
           trainable parameters (pennylane#4462 — raises
           ``NotImplementedError``). The embedding angles here *are*
           trainable, because the upstream squeeze linear trains end-to-end.
        2. Hardware faithfulness: real QPUs execute one circuit at a time —
           broadcast batching is a simulator-only shortcut, so the per-sample
           loop is the *more* honest model of parameter-shift gradient
           economics for this reference implementation (batch sizes here are
           small, so the simulator cost stays tractable).
        """
        bsz, seq, _ = h.shape
        n = self.config.n_qubits
        # tanh * pi bounds the embedding angles to one RY period.
        z = math.pi * torch.tanh(self.squeeze(h))
        flat = z.reshape(-1, n)  # (B*L, n) embedding angles
        # Per-sample circuit execution (see docstring); expvals in [-1, 1].
        q = torch.stack([self.qlayer(sample) for sample in flat])
        return self.expand(q.reshape(bsz, seq, n))


class _ElementwiseScale(nn.Module):
    """One classical pseudo-layer with exactly n_qubits parameters.

    ``tanh(x * w)`` per channel: a bounded nonlinearity with one weight per
    feature, mirroring one VQC entangler layer's one-RY-per-qubit parameter
    budget so the control's middle parameter count matches exactly.
    """

    def __init__(self, n_features: int) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(n_features))

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        """Bounded elementwise transform, output in (-1, 1) like ⟨Z⟩ values."""
        return torch.tanh(x * self.weight)


class ClassicalControlAdapter(nn.Module):
    """Control adapter: identical shell, classical middle, matched parameters.

    Workflow Stage 3 step 5: identical architecture with the quantum block
    replaced by a classical block of matched parameter count — squeeze and
    expand linears are identical to :class:`QuantumAdapterHead`; the middle
    stacks ``q_depth`` :class:`_ElementwiseScale` layers for exactly
    ``q_depth * n_qubits`` trainable parameters, equal to the VQC's weight
    tensor. The research doc §5 item (ii) prediction: the hybrid *matches*,
    not beats, this control (expected null result).
    """

    def __init__(self, d_model: int, config: HybridConfig) -> None:
        """Build the parameter-matched classical counterpart."""
        super().__init__()
        if not TORCH_AVAILABLE:
            raise ImportError(INSTALL_MESSAGE)
        self.config = config
        n = config.n_qubits
        self.squeeze = nn.Linear(d_model, n)
        self.expand = nn.Linear(n, d_model)
        self.middle = nn.ModuleList(
            _ElementwiseScale(n) for _ in range(config.q_depth)
        )

    def middle_parameters(self) -> list["torch.Tensor"]:
        """The matched middle parameters (interface shared with quantum head)."""
        return [layer.weight for layer in self.middle]

    def forward(self, h: "torch.Tensor") -> "torch.Tensor":
        """Same shape contract as the quantum adapter: (B, L, D) -> (B, L, D)."""
        z = math.pi * torch.tanh(self.squeeze(h))
        for layer in self.middle:
            z = layer(z)
        return self.expand(z)


class HybridModel(nn.Module):
    """Stage 1 transformer + adapter (quantum or control) in the residual stream.

    Forward: classical features -> ``h + adapter(h)`` -> classical output
    head. With a :class:`QuantumAdapterHead`, one ``loss.backward()`` realizes
    the full Stage 3 loop: classical forward pass, quantum gradient
    estimation for the circuit parameters, classical weight update (by the
    caller's optimizer step).
    """

    def __init__(
        self,
        model_config: ModelConfig,
        adapter: nn.Module,
        freeze_base: bool = False,
    ) -> None:
        """Compose the base transformer with an adapter; optionally freeze base.

        ``freeze_base=True`` reproduces the research doc §5 item (ii) setting
        (small VQC head on a *frozen* classical LM); the default trains
        end-to-end since the Stage 1 model starts untrained here.
        """
        super().__init__()
        if not TORCH_AVAILABLE:
            raise ImportError(INSTALL_MESSAGE)
        self.base = MinimalTransformer(model_config)
        self.adapter = adapter
        if freeze_base:
            for param in self.base.parameters():
                param.requires_grad_(False)

    def forward(self, tokens: "torch.Tensor") -> "torch.Tensor":
        """Next-token logits with the adapter applied pre-head, residually."""
        h = self.base.features(tokens)
        h = h + self.adapter(h)
        return self.base.output_head(h)


# --------------------------------------------------------------------------
# Training (workflow Stage 3 steps 3-6)
# --------------------------------------------------------------------------
def train_hybrid(
    model: HybridModel,
    dataset: SyntheticDataset,
    device_name: str,
    *,
    steps: int = 200,
    batch_size: int = 8,
    lr: float = 3e-4,
    seed: int = 42,
    label: str = "hybrid",
    log_every: int = 25,
) -> dict[str, Any]:
    """Train one model, logging wall-clock, grad variance, circuit executions.

    Works for both the hybrid model (quantum adapter) and the classical
    control: the adapter's ``middle_parameters()`` interface supplies the
    parameters whose per-step gradient variance is recorded (variance across
    gradient components — the analytic-vs-shot gap in this series is the
    Stage 3 step 4 recorded result). For quantum adapters, circuit executions
    are measured with ``qml.Tracker`` on the bound device where supported.

    Raises ``RuntimeError`` if gradients fail to reach the adapter middle
    parameters on the first step (workflow Stage 3 acceptance: gradients
    reach quantum parameters via ``loss.backward()``).
    """
    if not TORCH_AVAILABLE:
        raise ImportError(INSTALL_MESSAGE)
    bound_device = getattr(model.adapter, "device_ref", None)
    if bound_device is not None and getattr(model.adapter, "config", None) is not None:
        bound_name = model.adapter.config.device_name
        if bound_name != device_name:
            raise ValueError(
                f"device_name={device_name!r} does not match the adapter's "
                f"bound device {bound_name!r} (binding happens in "
                "QuantumAdapterHead.__init__)."
            )

    torch.manual_seed(seed)
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    batch_iter = dataset.batches(
        batch_size, generator=torch.Generator().manual_seed(seed)
    )

    losses: list[float] = []
    wall_clock: list[float] = []
    grad_variance: list[float] = []
    tracker = None
    if bound_device is not None and PENNYLANE_AVAILABLE:
        try:  # Tracker support varies by device; counts are best-effort.
            tracker = qml.Tracker(bound_device)
            tracker.active = True
        except Exception:  # pragma: no cover - device without tracker support
            tracker = None

    model.train()
    print(f"[stage-3] training '{label}' on {device_name} for {steps} steps ...")
    for step in range(steps):
        t0 = time.perf_counter()
        inputs, targets = next(batch_iter)
        inputs, targets = inputs[:, : dataset.seq_len], targets[:, : dataset.seq_len]
        logits = model(inputs)
        loss = loss_fn(logits.reshape(-1, dataset.vocab_size), targets.reshape(-1))
        loss.backward()  # quantum gradient estimation happens inside, via the bridge

        middle = model.adapter.middle_parameters()
        if step == 0:
            for param in middle:
                if param.grad is None:
                    raise RuntimeError(
                        "gradient did not reach the adapter parameters via "
                        "loss.backward() — the PennyLane+PyTorch bridge is "
                        "broken (workflow Stage 3 acceptance criterion)."
                    )
        grad_vec = torch.cat([p.grad.detach().flatten() for p in middle])
        grad_variance.append(float(grad_vec.var(unbiased=False)))

        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(float(loss.detach()))
        wall_clock.append(time.perf_counter() - t0)
        if log_every and (step % log_every == 0 or step == steps - 1):
            print(f"  [{label}] step {step:4d}  loss {losses[-1]:.4f}  "
                  f"wall {wall_clock[-1]*1e3:.1f} ms")

    executions_total: int | None = None
    if tracker is not None:
        tracker.active = False
        executions_total = int(tracker.totals.get("executions", 0))

    return {
        "label": label,
        "device": device_name if bound_device is not None else "classical",
        "loss_curve": losses,
        "final_loss": losses[-1],
        "mean_loss_last_25": statistics.fmean(losses[-25:]),
        "per_step_wall_clock_s": wall_clock,
        "grad_variance_per_step": grad_variance,
        "circuit_executions_total": executions_total,
        "wall_clock_caveat": (
            "Simulator wall-clock validates correctness only; it is never "
            "evidence about quantum hardware speed (workflow ground rule)."
        ),
    }


# --------------------------------------------------------------------------
# Run orchestration: hybrid + control, JSON log
# --------------------------------------------------------------------------
def run_experiment(
    hybrid_cfg: HybridConfig, out_path: Path
) -> dict[str, Any]:
    """Run hybrid and matched-parameter control; write hybrid_run_log.json."""
    model_cfg = ModelConfig(seq_len=hybrid_cfg.seq_len)
    dataset = make_synthetic_dataset(
        vocab_size=model_cfg.vocab_size,
        seq_len=hybrid_cfg.seq_len,
        n_examples=2048,
        seed=hybrid_cfg.seed,
    )

    if hybrid_cfg.diff_method == "adjoint":
        print(f"\n{ADJOINT_NOTE}\n")

    quantum_adapter = QuantumAdapterHead(model_cfg.d_model, hybrid_cfg)
    control_adapter = ClassicalControlAdapter(model_cfg.d_model, hybrid_cfg)
    q_middle = sum(p.numel() for p in quantum_adapter.middle_parameters())
    c_middle = sum(p.numel() for p in control_adapter.middle_parameters())
    assert q_middle == c_middle, (
        f"control mismatch: quantum middle {q_middle} != control middle "
        f"{c_middle} parameters (workflow Stage 3 step 5 requires a match)"
    )

    hybrid_result = train_hybrid(
        HybridModel(model_cfg, quantum_adapter, hybrid_cfg.freeze_base),
        dataset,
        hybrid_cfg.device_name,
        steps=hybrid_cfg.steps,
        batch_size=hybrid_cfg.batch_size,
        lr=hybrid_cfg.lr,
        seed=hybrid_cfg.seed,
        label="hybrid_vqc",
    )
    control_result = train_hybrid(
        HybridModel(model_cfg, control_adapter, hybrid_cfg.freeze_base),
        dataset,
        "classical-control",
        steps=hybrid_cfg.steps,
        batch_size=hybrid_cfg.batch_size,
        lr=hybrid_cfg.lr,
        seed=hybrid_cfg.seed,
        label="classical_control",
    )

    log: dict[str, Any] = {
        "schema": "hybrid_run_log.v1",
        "generated_by": "hybrid_training_loop.py (workflow Stage 3)",
        "model_config": asdict(model_cfg),
        "hybrid_config": asdict(hybrid_cfg),
        "diff_method": hybrid_cfg.diff_method,
        "mode": "shot-based" if hybrid_cfg.shots else "analytic",
        "adjoint_note": ADJOINT_NOTE,
        "barren_plateau_constraint": (
            f"quantum block: {hybrid_cfg.n_qubits} qubits (<= {MAX_QUBITS}), "
            f"depth {hybrid_cfg.q_depth} = O(log n), local single-qubit "
            "observables — research doc §3.3-3.4 [Proven] (McClean et al.; "
            "Cerezo et al.)"
        ),
        "quantum_middle_param_count": q_middle,
        "control_middle_param_count": c_middle,
        "expected_executions_per_step_parameter_shift": (
            hybrid_cfg.expected_executions_per_step
        ),
        "execution_scaling_note": (
            "Expected executions per sample in shift mode = 1 + 2*(d_q + n) "
            f"= {hybrid_cfg.expected_executions_per_sample} (d_q = "
            f"{hybrid_cfg.quantum_param_count} circuit weights + "
            f"{hybrid_cfg.n_qubits} trainable embedding angles); per step = "
            f"{hybrid_cfg.expected_executions_per_step} across "
            f"{hybrid_cfg.batch_size * hybrid_cfg.seq_len} per-sample "
            "circuits (per-sample, not broadcast: pennylane#4462; also the "
            "hardware-faithful model) — the O(d) economics of research doc "
            "§3.1 [Proven]; at hardware precision eps=1e-2 each expectation "
            f"additionally needs ~{shots_for_precision(1e-2):,} shots."
        ),
        "hybrid": hybrid_result,
        "control": control_result,
        "comparison": {
            "hybrid_final_loss": hybrid_result["final_loss"],
            "control_final_loss": control_result["final_loss"],
            "expected_result": (
                "Null result expected: hybrid matches, not beats, the "
                "matched-parameter classical control (research doc §5 item "
                "(ii) — valuable either way) [Theoretical] experiment design."
            ),
            "claim_policy": (
                "No hybrid-superiority claim is made or logged unless it "
                "exceeds the control by > 2 sigma across >= 5 seeds "
                "(workflow Stage 3 acceptance); this single-seed run cannot "
                "and does not make one."
            ),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(log, indent=2))
    print(f"\n[stage-3] wrote run log: {out_path}")
    print(f"  hybrid final loss : {hybrid_result['final_loss']:.4f}")
    print(f"  control final loss: {control_result['final_loss']:.4f}")
    print(f"  {log['comparison']['expected_result']}")
    return log


# --------------------------------------------------------------------------
# Dependency-free dry run
# --------------------------------------------------------------------------
def print_plan(cfg: HybridConfig) -> None:
    """Print the execution plan using only dependency-free accounting."""
    d_q = cfg.quantum_param_count
    print("[stage-3] hybrid training plan (dry run — no heavy deps needed)")
    print(f"  device              : {cfg.device_name} (shots="
          f"{cfg.shots or 'analytic'})  diff_method={cfg.diff_method}")
    print(f"  quantum block       : {cfg.n_qubits} qubits (limit {MAX_QUBITS}, "
          f"workflow Stage 3 step 2), depth {cfg.q_depth} = O(log n)")
    print(f"  cost observables    : local single-qubit <Z_w> "
          "(research doc §3.3-3.4 [Proven], Cerezo et al.)")
    print(f"  circuit parameters  : d_q = {d_q} (one RY per qubit per layer)")
    print(f"  executions/sample   : 1 + 2*(d_q + n) = "
          f"{cfg.expected_executions_per_sample} in parameter-shift mode "
          "(O(d), research doc §3.1 [Proven]; the n embedding angles are "
          "trainable because the squeeze linear trains end-to-end)")
    print(f"  executions/step     : {cfg.expected_executions_per_step} "
          f"({cfg.batch_size * cfg.seq_len} per-sample circuits/step — "
          "per-sample, not broadcast: pennylane#4462, and hardware runs "
          "one circuit at a time anyway)")
    print(f"  shots @ eps=1e-2    : {shots_for_precision(1e-2):,} per expectation "
          "value on hardware (O(1/eps^2), §3.1 [Proven])")
    print(f"  training            : {cfg.steps} steps, batch {cfg.batch_size}, "
          f"seq_len {cfg.seq_len}, AdamW lr={cfg.lr}, seed {cfg.seed}")
    print("  control experiment  : classical adapter with exactly "
          f"{d_q} matched middle parameters; expected null result "
          "(research doc §5 item (ii))")
    print(f"  {ADJOINT_NOTE}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _default_out_path() -> Path:
    """Default log path: qml-accelerator/benchmarks/hybrid_run_log.json."""
    return Path(__file__).resolve().parents[1] / "benchmarks" / "hybrid_run_log.json"


def build_arg_parser() -> argparse.ArgumentParser:
    """CLI per workflow Stage 3 acceptance: --device, --steps (+ extras)."""
    parser = argparse.ArgumentParser(
        description=(
            "Stage 3 hybrid training loop (docs/workflows/01-qml-workflow.md): "
            "classical forward -> quantum gradient estimation -> classical update."
        )
    )
    parser.add_argument(
        "--device",
        choices=("default.qubit", "lightning.qubit"),
        default="default.qubit",
        help="PennyLane simulator device (default per Stage 3 spec)",
    )
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument(
        "--shots",
        type=int,
        default=0,
        help="0 = analytic mode; e.g. 1024 enables shot-based mode "
        "(workflow Stage 3 step 4)",
    )
    parser.add_argument("--n-qubits", type=int, default=8)
    parser.add_argument("--q-depth", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seq-len", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument(
        "--freeze-base",
        action="store_true",
        help="freeze the classical LM (research doc §5 item (ii) variant)",
    )
    parser.add_argument("--out", type=Path, default=_default_out_path())
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the execution plan without importing/needing torch or pennylane",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the Stage 3 hybrid-vs-control experiment (or its dry-run plan)."""
    args = build_arg_parser().parse_args(argv)
    try:
        cfg = HybridConfig(
            n_qubits=args.n_qubits,
            q_depth=args.q_depth,
            device_name=args.device,
            shots=args.shots or None,
            steps=args.steps,
            batch_size=args.batch_size,
            seq_len=args.seq_len,
            lr=args.lr,
            seed=args.seed,
            freeze_base=args.freeze_base,
        )
    except ValueError as exc:
        print(f"ERROR: invalid configuration: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print_plan(cfg)
        return 0
    if not (TORCH_AVAILABLE and PENNYLANE_AVAILABLE):
        print_plan(cfg)
        print(f"\n{INSTALL_MESSAGE}", file=sys.stderr)
        return 1
    try:
        run_experiment(cfg, args.out)
    except Exception as exc:  # device plugins (lightning) may be missing
        if "lightning" in str(exc).lower() and args.device == "lightning.qubit":
            print(
                f"ERROR: {exc}\nlightning.qubit unavailable — install "
                "'pennylane-lightning>=0.38' or rerun with "
                "--device default.qubit.",
                file=sys.stderr,
            )
            return 1
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
