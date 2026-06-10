#!/usr/bin/env python3
"""Stage 1 — Classical baseline: minimal profiled PyTorch transformer.

Implements workflow Stage 1 of ``docs/workflows/01-qml-workflow.md``:

* ``MinimalTransformer(n_layers=4, d_model=128, n_heads=8)`` in pure PyTorch
  (no ``nn.Transformer`` shortcut — every op is instrumented individually),
  built from the workflow-mandated modules ``QKVProjection``,
  ``ScaledDotProductAttention``, ``MLP`` (4x expansion, matching the research
  doc §4.0 accounting), and ``OutputHead``.
* ``make_synthetic_dataset(vocab_size=512, seq_len=64, n_examples=8192,
  seed=42)`` — a seeded next-token-prediction task over a k-th order Markov
  source (k=1 instance), so loss curves are meaningful.
* ``train(model, dataset, batch_size=64, steps=500)`` with AdamW and
  cross-entropy, asserting the workflow's >= 30% loss-decrease sanity check.
* Per-operation profiling via explicit ``time.perf_counter()`` wrappers around
  the four target ops — **attention QKV matmul**, **softmax**, **MLP**, and
  **gradient update** (backward + optimizer step) — recording mean/p50/p95
  over the steady-state window (steps 100–500), plus FLOP estimates from the
  research doc §4.0 formulas (O(B·L·d_model²) for QKV/MLP projections,
  O(B·L²·d_model) for attention scores; backward ≈ 2× forward).
* ``dump_baseline(path)`` emitting ``classical_baseline.json`` with schema
  ``{hardware, torch_version, model_config, op_timings, flop_estimates,
  loss_curve}``.

Epistemic note (tags per the research doc convention): everything in this file
is classical engineering — the only scientific claims embedded here are the
**[Proven]** FLOP-accounting formulas of research doc §4.0, which the
``estimate_flops`` docstring cites. The timings this module measures are the
anchor for every later quantum comparison (workflow Stage 4/5); per the
workflow ground rules, they are honest wall-clock measurements of classical
hardware, never to be conflated with simulator timings of quantum circuits.

Dependency policy: PyTorch is required to *run* anything, but this module is
importable without it (a minimal ``nn.Module`` stub is substituted) so the
coupled Stage 2/3 modules can perform dependency-free resource accounting and
``--dry-run`` planning. The ``__main__`` entry point fails gracefully with an
install message when PyTorch is absent.

Usage::

    python classical_transformer.py --steps 500 --profile \
        --out ../benchmarks/classical_baseline.json
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

# --------------------------------------------------------------------------
# Guarded heavy import. torch is mandatory at runtime but optional at import
# time so that hybrid_training_loop.py / quantum_attention.py can import the
# config dataclasses and FLOP formulas for dependency-free planning.
# --------------------------------------------------------------------------
try:
    import torch
    from torch import nn

    TORCH_AVAILABLE: bool = True
except ImportError:  # pragma: no cover - exercised only in torch-less envs
    TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]

    class _NnStub:
        """Minimal stand-in so class definitions below stay importable.

        Only ``nn.Module`` is needed at class-creation time; no stubbed class
        is ever *instantiated* without torch (``main()`` checks first).
        """

        class Module:  # noqa: D106 - intentional bare stand-in
            pass

    nn = _NnStub()  # type: ignore[assignment]

TORCH_INSTALL_MESSAGE = (
    "ERROR: PyTorch is required to run this script (workflow prerequisite: "
    "torch >= 2.3).\n"
    "Install with:  pip install 'torch>=2.3'\n"
    "The module itself imports without torch so that Stage 2/3 modules can do "
    "dependency-free resource accounting (see docs/workflows/01-qml-workflow.md)."
)

# Canonical op names — these are the exact JSON keys mandated by workflow
# Stage 1 step 5 and consumed by Stage 4's complexity_analysis.py.
OP_QKV_MATMUL = "qkv_matmul"
OP_SOFTMAX = "softmax"
OP_MLP = "mlp"
OP_GRAD_UPDATE = "grad_update"
TARGET_OPS: tuple[str, ...] = (OP_QKV_MATMUL, OP_SOFTMAX, OP_MLP, OP_GRAD_UPDATE)

# Workflow Stage 1 step 4: steady-state window is steps 100-500.
STEADY_STATE_START_STEP = 100


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
@dataclass
class ModelConfig:
    """Hyperparameters for the Stage 1 baseline (workflow Stage 1 step 1)."""

    n_layers: int = 4
    d_model: int = 128
    n_heads: int = 8
    vocab_size: int = 512
    seq_len: int = 64
    mlp_expansion: int = 4  # "customary 4x expansion" — research doc §4.0

    def __post_init__(self) -> None:
        if self.d_model % self.n_heads != 0:
            raise ValueError(
                f"d_model={self.d_model} must be divisible by n_heads={self.n_heads}"
            )

    @property
    def d_head(self) -> int:
        """Per-head dimension."""
        return self.d_model // self.n_heads


# --------------------------------------------------------------------------
# Per-operation timing
# --------------------------------------------------------------------------
class OpTimer:
    """Wall-clock profiler for the four workflow target ops.

    Records ``(step, seconds)`` samples per op via :meth:`track`; the training
    loop advances :attr:`current_step` so summaries can be restricted to the
    steady-state window (workflow Stage 1 step 4: steps 100-500).

    Parameters
    ----------
    sync_fn:
        Optional callable invoked before reading the clock (e.g.
        ``torch.cuda.synchronize`` when timing CUDA kernels, which launch
        asynchronously). ``None`` for CPU runs.
    """

    def __init__(self, sync_fn: Callable[[], None] | None = None) -> None:
        self.records: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self.current_step: int = 0
        self.enabled: bool = True
        self._sync_fn = sync_fn

    @contextmanager
    def track(self, op_name: str) -> Iterator[None]:
        """Context manager timing one occurrence of ``op_name``."""
        if not self.enabled:
            yield
            return
        if self._sync_fn is not None:
            self._sync_fn()
        t0 = time.perf_counter()
        try:
            yield
        finally:
            if self._sync_fn is not None:
                self._sync_fn()
            self.records[op_name].append((self.current_step, time.perf_counter() - t0))

    @staticmethod
    def _percentile(sorted_vals: list[float], q: float) -> float:
        """Nearest-rank percentile of a pre-sorted list (q in [0, 1])."""
        if not sorted_vals:
            return 0.0
        idx = min(len(sorted_vals) - 1, round(q * (len(sorted_vals) - 1)))
        return sorted_vals[idx]

    def summary(self, window_start_step: int = 0) -> dict[str, dict[str, float]]:
        """Mean/p50/p95 (seconds) per op over samples at step >= window start."""
        out: dict[str, dict[str, float]] = {}
        for op, samples in self.records.items():
            vals = sorted(s for (step, s) in samples if step >= window_start_step)
            if not vals:
                continue
            out[op] = {
                "mean_s": statistics.fmean(vals),
                "p50_s": self._percentile(vals, 0.50),
                "p95_s": self._percentile(vals, 0.95),
                "n_samples": float(len(vals)),
            }
        return out


@contextmanager
def _maybe_track(timer: OpTimer | None, op_name: str) -> Iterator[None]:
    """Track ``op_name`` on ``timer`` if a timer is attached, else no-op."""
    if timer is None:
        yield
    else:
        with timer.track(op_name):
            yield


# --------------------------------------------------------------------------
# Model modules (workflow Stage 1 step 1 module list, verbatim names)
# --------------------------------------------------------------------------
class QKVProjection(nn.Module):
    """Fused Q/K/V linear projection, timed as the ``qkv_matmul`` op.

    Cost O(B·L·d_model²) per layer — research doc §4.0 [Proven] accounting.
    """

    def __init__(self, config: ModelConfig, timer: OpTimer | None = None) -> None:
        super().__init__()
        self.config = config
        self.timer = timer
        self.qkv = nn.Linear(config.d_model, 3 * config.d_model, bias=False)

    def forward(
        self, x: "torch.Tensor"
    ) -> tuple["torch.Tensor", "torch.Tensor", "torch.Tensor"]:
        """Project ``x`` (B, L, d_model) to per-head q, k, v of (B, H, L, d_head)."""
        bsz, seq, _ = x.shape
        cfg = self.config
        with _maybe_track(self.timer, OP_QKV_MATMUL):
            qkv = self.qkv(x)  # the profiled matmul: (B, L, 3*d_model)
        q, k, v = qkv.split(cfg.d_model, dim=-1)

        def _heads(t: "torch.Tensor") -> "torch.Tensor":
            return t.view(bsz, seq, cfg.n_heads, cfg.d_head).transpose(1, 2)

        return _heads(q), _heads(k), _heads(v)


class ScaledDotProductAttention(nn.Module):
    """Causal scaled dot-product attention with the softmax timed separately.

    The QKᵀ score matmul and attention-weighted V each cost O(B·L²·d_model)
    per layer (research doc §4.0 [Proven] accounting); the softmax over the
    (B, H, L, L) score tensor is the workflow's second profiled op.
    """

    def __init__(self, config: ModelConfig, timer: OpTimer | None = None) -> None:
        super().__init__()
        self.config = config
        self.timer = timer
        # Upper-triangular True entries mark *disallowed* (future) positions.
        mask = torch.triu(
            torch.ones(config.seq_len, config.seq_len, dtype=torch.bool), diagonal=1
        )
        self.register_buffer("causal_mask", mask, persistent=False)

    def forward(
        self, q: "torch.Tensor", k: "torch.Tensor", v: "torch.Tensor"
    ) -> "torch.Tensor":
        """Apply causal attention; inputs (B, H, L, d_head) -> (B, L, d_model)."""
        bsz, n_heads, seq, d_head = q.shape
        scores = (q @ k.transpose(-2, -1)) / math.sqrt(d_head)  # O(B·L²·d_model)
        scores = scores.masked_fill(self.causal_mask[:seq, :seq], float("-inf"))
        with _maybe_track(self.timer, OP_SOFTMAX):
            attn = torch.softmax(scores, dim=-1)  # the profiled softmax
        out = attn @ v  # attention-weighted values, O(B·L²·d_model)
        return out.transpose(1, 2).contiguous().view(bsz, seq, n_heads * d_head)


class MLP(nn.Module):
    """Position-wise feed-forward block with 4x expansion, timed as ``mlp``.

    Cost O(B·L·d_model²) per layer with the 4x constant — research doc §4.0.
    """

    def __init__(self, config: ModelConfig, timer: OpTimer | None = None) -> None:
        super().__init__()
        self.timer = timer
        hidden = config.mlp_expansion * config.d_model
        self.fc_in = nn.Linear(config.d_model, hidden)
        self.act = nn.GELU()
        self.fc_out = nn.Linear(hidden, config.d_model)

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        """Apply the two profiled MLP matmuls (B, L, d_model) -> same shape."""
        with _maybe_track(self.timer, OP_MLP):
            return self.fc_out(self.act(self.fc_in(x)))


class TransformerBlock(nn.Module):
    """Pre-LayerNorm transformer block: attention sublayer + MLP sublayer."""

    def __init__(self, config: ModelConfig, timer: OpTimer | None = None) -> None:
        super().__init__()
        self.ln1 = nn.LayerNorm(config.d_model)
        self.qkv_proj = QKVProjection(config, timer)
        self.attention = ScaledDotProductAttention(config, timer)
        self.out_proj = nn.Linear(config.d_model, config.d_model, bias=False)
        self.ln2 = nn.LayerNorm(config.d_model)
        self.mlp = MLP(config, timer)

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        """Residual attention then residual MLP."""
        q, k, v = self.qkv_proj(self.ln1(x))
        x = x + self.out_proj(self.attention(q, k, v))
        x = x + self.mlp(self.ln2(x))
        return x


class OutputHead(nn.Module):
    """Final LayerNorm + vocabulary projection to next-token logits."""

    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        self.ln_final = nn.LayerNorm(config.d_model)
        self.proj = nn.Linear(config.d_model, config.vocab_size, bias=False)

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        """Map hidden states (B, L, d_model) to logits (B, L, vocab_size)."""
        return self.proj(self.ln_final(x))


class MinimalTransformer(nn.Module):
    """Minimal causal-LM transformer: 4 layers, d_model=128, 8 heads (default).

    Built strictly from the workflow Stage 1 modules so each profiled op is
    individually instrumented. Exposes :meth:`features` (hidden states before
    the head) as the seam used by Stage 3's ``HybridModel`` to insert a
    quantum adapter into the residual stream.
    """

    def __init__(self, config: ModelConfig | None = None, timer: OpTimer | None = None) -> None:
        super().__init__()
        self.config = config or ModelConfig()
        self.timer = timer
        cfg = self.config
        self.token_embedding = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.position_embedding = nn.Embedding(cfg.seq_len, cfg.d_model)
        self.blocks = nn.ModuleList(
            TransformerBlock(cfg, timer) for _ in range(cfg.n_layers)
        )
        self.output_head = OutputHead(cfg)

    def features(self, tokens: "torch.Tensor") -> "torch.Tensor":
        """Hidden states (B, L, d_model) after the final block, before the head."""
        seq = tokens.shape[1]
        positions = torch.arange(seq, device=tokens.device)
        x = self.token_embedding(tokens) + self.position_embedding(positions)
        for block in self.blocks:
            x = block(x)
        return x

    def forward(self, tokens: "torch.Tensor") -> "torch.Tensor":
        """Next-token logits (B, L, vocab_size) for token ids (B, L)."""
        return self.output_head(self.features(tokens))

    def parameter_count(self) -> int:
        """Total trainable parameters."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


# --------------------------------------------------------------------------
# Synthetic dataset (workflow Stage 1 step 2)
# --------------------------------------------------------------------------
@dataclass
class SyntheticDataset:
    """Seeded synthetic next-token-prediction corpus.

    ``tokens`` has shape (n_examples, seq_len + 1); inputs are
    ``tokens[:, :-1]`` and shifted targets are ``tokens[:, 1:]``.
    """

    tokens: "torch.Tensor"
    vocab_size: int
    seq_len: int
    seed: int
    markov_order: int
    optimal_cross_entropy_nats: float

    @property
    def n_examples(self) -> int:
        """Number of sequences in the corpus."""
        return int(self.tokens.shape[0])

    def batches(
        self, batch_size: int, generator: "torch.Generator | None" = None
    ) -> Iterator[tuple["torch.Tensor", "torch.Tensor"]]:
        """Infinite iterator of shuffled (inputs, targets) batches."""
        while True:
            perm = torch.randperm(self.n_examples, generator=generator)
            for i in range(0, self.n_examples - batch_size + 1, batch_size):
                idx = perm[i : i + batch_size]
                chunk = self.tokens[idx]
                yield chunk[:, :-1], chunk[:, 1:]


def make_synthetic_dataset(
    vocab_size: int = 512,
    seq_len: int = 64,
    n_examples: int = 8192,
    seed: int = 42,
    n_successors: int = 4,
) -> SyntheticDataset:
    """Generate a seeded k-th order Markov corpus (k=1) for next-token prediction.

    Each token has exactly ``n_successors`` allowed successors with a fixed
    peaked distribution (default [0.70, 0.15, 0.10, 0.05]), giving the task a
    learnable structure: the optimal cross-entropy equals the source entropy
    (~0.92 nats at the defaults), far below the ln(vocab_size) ≈ 6.24 nats of
    an untrained model — so the workflow's >= 30% loss-decrease sanity check is
    comfortably reachable in 500 steps.

    All randomness flows through one ``torch.Generator`` seeded with ``seed``
    (workflow acceptance: reproducible runs).
    """
    if not TORCH_AVAILABLE:
        raise ImportError(TORCH_INSTALL_MESSAGE)
    gen = torch.Generator().manual_seed(seed)

    # Transition structure: successors[v] lists the n_successors tokens
    # reachable from v; probs is the shared peaked successor distribution.
    successors = torch.randint(
        0, vocab_size, (vocab_size, n_successors), generator=gen
    )
    raw = torch.tensor([0.70, 0.15, 0.10, 0.05][:n_successors], dtype=torch.float64)
    probs = raw / raw.sum()
    entropy = float(-(probs * probs.log()).sum())  # optimal CE in nats

    tokens = torch.empty((n_examples, seq_len + 1), dtype=torch.long)
    tokens[:, 0] = torch.randint(0, vocab_size, (n_examples,), generator=gen)
    expanded = probs.expand(n_examples, -1)
    for t in range(seq_len):
        choice = torch.multinomial(expanded, 1, generator=gen).squeeze(1)
        tokens[:, t + 1] = successors[tokens[:, t], choice]

    return SyntheticDataset(
        tokens=tokens,
        vocab_size=vocab_size,
        seq_len=seq_len,
        seed=seed,
        markov_order=1,
        optimal_cross_entropy_nats=entropy,
    )


# --------------------------------------------------------------------------
# Training loop (workflow Stage 1 step 3) + grad_update profiling (step 4)
# --------------------------------------------------------------------------
def train(
    model: MinimalTransformer,
    dataset: SyntheticDataset,
    batch_size: int = 64,
    steps: int = 500,
    lr: float = 3e-4,
    seed: int = 42,
    timer: OpTimer | None = None,
    log_every: int = 50,
    enforce_loss_decrease: bool = True,
) -> list[float]:
    """Train with AdamW + cross-entropy; return the per-step loss curve.

    The ``grad_update`` op (backward + optimizer step, per workflow Stage 1
    step 4) is timed on ``timer``. When ``steps >= 500`` and
    ``enforce_loss_decrease`` is set, raises ``RuntimeError`` unless mean loss
    over the final 10 steps is >= 30% below the mean over the first 10 — the
    workflow Stage 1 step 3 sanity check that the baseline actually learns.
    """
    if not TORCH_AVAILABLE:
        raise ImportError(TORCH_INSTALL_MESSAGE)
    torch.manual_seed(seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    batch_gen = torch.Generator().manual_seed(seed)
    batch_iter = dataset.batches(batch_size, generator=batch_gen)

    losses: list[float] = []
    model.train()
    for step in range(steps):
        if timer is not None:
            timer.current_step = step
        inputs, targets = next(batch_iter)
        logits = model(inputs)
        loss = loss_fn(
            logits.reshape(-1, dataset.vocab_size), targets.reshape(-1)
        )
        with _maybe_track(timer, OP_GRAD_UPDATE):
            loss.backward()
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        losses.append(float(loss.detach()))
        if log_every and (step % log_every == 0 or step == steps - 1):
            print(f"  step {step:4d}  loss {losses[-1]:.4f}")

    if enforce_loss_decrease and steps >= 500:
        head = statistics.fmean(losses[:10])
        tail = statistics.fmean(losses[-10:])
        decrease = (head - tail) / head
        if decrease < 0.30:
            raise RuntimeError(
                f"Sanity check failed (workflow Stage 1 step 3): loss decreased "
                f"only {decrease:.1%} (< 30%) from {head:.4f} to {tail:.4f}."
            )
        print(f"  sanity check OK: loss decreased {decrease:.1%} (>= 30% required)")
    return losses


# --------------------------------------------------------------------------
# FLOP estimates (research doc §4.0 formulas; workflow Stage 1 step 4)
# --------------------------------------------------------------------------
def estimate_flops(config: ModelConfig, batch_size: int) -> dict[str, Any]:
    """Per-training-step FLOP estimates from the research doc §4.0 formulas.

    [Proven] accounting (research doc §4.0, "Where the FLOPs Actually Are"):
    per layer the forward pass costs — QKV projections O(B·L·d_model²),
    attention scores QKᵀ O(B·L²·d_model), attention-weighted values
    O(B·L²·d_model), output projection O(B·L·d_model²), MLP O(B·L·d_model²)
    with the customary 4x expansion; the backward pass costs ≈ 2x the forward.
    Constants below use the standard 2-FLOPs-per-multiply-accumulate rule.
    The softmax entry is a documented heuristic (~5 elementwise FLOPs per
    score entry), included because softmax is a profiled op, not a §4.0 term.

    The formula strings are emitted verbatim so Stage 4's
    ``complexity_analysis.py --verify`` can cross-check against the research
    doc mechanically.
    """
    b, length, d = batch_size, config.seq_len, config.d_model
    n_layers, expansion = config.n_layers, config.mlp_expansion
    qkv = 2 * b * length * d * (3 * d) * n_layers
    attn_scores = 2 * 2 * b * length * length * d * n_layers  # QK^T + attn@V
    softmax = 5 * b * config.n_heads * length * length * n_layers
    mlp = 2 * 2 * b * length * d * (expansion * d) * n_layers
    out_proj = 2 * b * length * d * d * n_layers
    head = 2 * b * length * d * config.vocab_size
    forward_total = qkv + attn_scores + softmax + mlp + out_proj + head
    return {
        OP_QKV_MATMUL: qkv,
        "attention_scores": attn_scores,
        OP_SOFTMAX: softmax,
        OP_MLP: mlp,
        "output_projection": out_proj,
        "output_head": head,
        "forward_total": forward_total,
        OP_GRAD_UPDATE: 2 * forward_total,  # backward ≈ 2x forward (§4.0)
        "formulas": {
            OP_QKV_MATMUL: "O(B*L*d_model^2) per layer (research doc §4.0) [Proven]",
            "attention_scores": "O(B*L^2*d_model) per layer (QK^T + attn@V) (§4.0) [Proven]",
            OP_SOFTMAX: "~5*B*H*L^2 elementwise FLOPs per layer (heuristic; not a §4.0 term)",
            OP_MLP: "O(B*L*d_model^2) per layer, 4x expansion (§4.0) [Proven]",
            OP_GRAD_UPDATE: "backward ~= 2x forward (§4.0) [Proven]",
        },
    }


# --------------------------------------------------------------------------
# Baseline JSON emission (workflow Stage 1 step 5)
# --------------------------------------------------------------------------
def _hardware_info() -> dict[str, str]:
    """Host description recorded in the baseline JSON."""
    info = {
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "python_version": platform.python_version(),
        "device": "cpu",
    }
    if TORCH_AVAILABLE and torch.cuda.is_available():
        info["device"] = f"cuda:{torch.cuda.get_device_name(0)}"
    return info


def dump_baseline(
    path: str | Path,
    *,
    config: ModelConfig,
    op_timings: dict[str, dict[str, float]],
    flop_estimates: dict[str, Any],
    loss_curve: list[float],
    run_meta: dict[str, Any] | None = None,
) -> Path:
    """Write ``classical_baseline.json`` with the workflow Stage 1 schema.

    Top-level keys (workflow Stage 1 step 5, verbatim): ``hardware``,
    ``torch_version``, ``model_config``, ``op_timings`` (with the four keys
    ``qkv_matmul``/``softmax``/``mlp``/``grad_update``), ``flop_estimates``,
    ``loss_curve``. ``run_meta`` is an additive extra (steps, seed, window).
    """
    missing = [op for op in TARGET_OPS if op not in op_timings]
    if missing:
        raise ValueError(
            f"op_timings missing required keys {missing}; run with profiling "
            "enabled for enough steps to populate the steady-state window."
        )
    payload: dict[str, Any] = {
        "hardware": _hardware_info(),
        "torch_version": torch.__version__ if TORCH_AVAILABLE else "unavailable",
        "model_config": asdict(config),
        "op_timings": op_timings,
        "flop_estimates": flop_estimates,
        "loss_curve": loss_curve,
        "run_meta": run_meta or {},
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _default_out_path() -> Path:
    """Default baseline path: qml-accelerator/benchmarks/classical_baseline.json."""
    return Path(__file__).resolve().parents[1] / "benchmarks" / "classical_baseline.json"


def build_arg_parser() -> argparse.ArgumentParser:
    """Argparse CLI per the assignment: --steps, --profile, --out (+ extras)."""
    parser = argparse.ArgumentParser(
        description=(
            "Stage 1 classical transformer baseline "
            "(docs/workflows/01-qml-workflow.md)."
        )
    )
    parser.add_argument("--steps", type=int, default=500, help="training steps")
    parser.add_argument(
        "--profile",
        action="store_true",
        help="profile the four target ops and write classical_baseline.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_out_path(),
        help="output path for classical_baseline.json",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lr", type=float, default=3e-4)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Train (and optionally profile) the Stage 1 baseline end-to-end."""
    args = build_arg_parser().parse_args(argv)
    if not TORCH_AVAILABLE:
        print(TORCH_INSTALL_MESSAGE, file=sys.stderr)
        return 1

    config = ModelConfig()
    print(f"[stage-1] config: {config}")
    print(f"[stage-1] generating synthetic Markov dataset (seed={args.seed}) ...")
    dataset = make_synthetic_dataset(
        vocab_size=config.vocab_size, seq_len=config.seq_len, seed=args.seed
    )
    print(
        f"[stage-1] {dataset.n_examples} sequences; optimal cross-entropy "
        f"{dataset.optimal_cross_entropy_nats:.3f} nats "
        f"(untrained ~= ln(V) = {math.log(config.vocab_size):.3f})"
    )

    sync = torch.cuda.synchronize if torch.cuda.is_available() else None
    timer = OpTimer(sync_fn=sync) if args.profile else None
    model = MinimalTransformer(config, timer)
    print(f"[stage-1] parameters: {model.parameter_count():,}")

    print(f"[stage-1] training for {args.steps} steps (batch={args.batch_size}) ...")
    losses = train(
        model,
        dataset,
        batch_size=args.batch_size,
        steps=args.steps,
        lr=args.lr,
        seed=args.seed,
        timer=timer,
    )

    if args.profile and timer is not None:
        # Steady-state window: steps 100-500 per the workflow; clamp for
        # short runs so smoke tests still produce a (clearly labeled) summary.
        window_start = min(STEADY_STATE_START_STEP, max(0, args.steps // 5))
        summary = timer.summary(window_start)
        flops = estimate_flops(config, args.batch_size)
        out = dump_baseline(
            args.out,
            config=config,
            op_timings=summary,
            flop_estimates=flops,
            loss_curve=losses,
            run_meta={
                "steps": args.steps,
                "batch_size": args.batch_size,
                "seed": args.seed,
                "lr": args.lr,
                "steady_state_window_start_step": window_start,
            },
        )
        print(f"[stage-1] wrote baseline: {out}")
        for op in TARGET_OPS:
            s = summary[op]
            print(
                f"    {op:12s} mean {s['mean_s']*1e3:8.3f} ms   "
                f"p50 {s['p50_s']*1e3:8.3f} ms   p95 {s['p95_s']*1e3:8.3f} ms   "
                f"(n={int(s['n_samples'])})"
            )
    print(f"[stage-1] final loss: {losses[-1]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
