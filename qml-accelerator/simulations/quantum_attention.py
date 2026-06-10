#!/usr/bin/env python3
"""Stage 2 — Quantum circuit equivalents of the profiled classical ops.

Implements workflow Stage 2 of ``docs/workflows/01-qml-workflow.md``: one
class per profiled classical op, each exposing ``.circuit()``,
``.qubit_count()``, ``.gate_depth()``, and ``.resource_report()``:

* :class:`HHLMatVec` — toy-scale (2x2 / 4x4 Hermitian) linear solve via HHL
  (research doc §2.3), with the five Aaronson caveats enforced via
  :class:`HHLCaveatViolation`, not just documented.
* :class:`QuantumSoftmaxSampler` — softmax *approximation* via
  amplitude-encoded exp-logits and measurement sampling (research doc §4.2),
  reporting total-variation distance versus the exact softmax as a function
  of shot count S.
* :class:`ParameterShiftGradient` — gradient estimation for a small VQC
  (4–8 qubits, 2–3 layers, **local** cost function per Cerezo et al.,
  research doc §3.3–3.4) using the exact parameter-shift rule, counting the
  O(d) circuit executions per gradient step that invert the classical
  reverse-mode economics (research doc §3.1).

What is simulated vs. real — stated plainly
-------------------------------------------
Every circuit in this module targets PennyLane's ``default.qubit``
*statevector simulator* (research doc §5: practical ceiling ~30 qubits dense).
Nothing here measures quantum *hardware* behavior, and per the workflow ground
rules, simulator wall-clock times validate correctness only — they are never
evidence about hardware speed. The honest hardware-relevant outputs of this
module are the **resource reports**: logical-qubit counts, two-qubit
gate-depth bounds, state-preparation gate counts (the O(2^n) amplitude-
encoding wall, research doc §3.1 [Proven]), and readout sample counts at
ε ∈ {1e-1, 1e-2, 1e-3} (the Ω(n/ε²) tomography wall, research doc §4.4
[Proven]). The resource accounting is computable with *no* quantum
dependencies installed, by design.

Epistemic tags (research doc convention)
----------------------------------------
* HHL complexity Õ(log N · s²κ²/ε) as a state-output algorithm: **[Proven]**
  (research doc §2.3, ref [3]); end-to-end matvec advantage after the five
  caveats: **[Speculative]**.
* Amplitude encoding of 2^n arbitrary values costs O(2^n) gate depth:
  **[Proven]** (research doc §3.1).
* Parameter-shift rule exactness: **[Proven]**; O(d/ε²) hardware gradient
  economics: **[Proven]** for the standard measurement model (§3.1).
* Quantum softmax sampling as an estimation primitive: **[Theoretical]**;
  end-to-end trainability with its per-entry statistical noise:
  **[Speculative]** (research doc §4.2).

Dependency policy: ``numpy`` is needed for the HHL linear algebra and
``pennylane`` for circuit construction/simulation; both imports are guarded so
resource accounting and the ``__main__`` dry-run degrade gracefully.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# --------------------------------------------------------------------------
# Guarded heavy imports (workflow prerequisite: pennylane >= 0.38)
# --------------------------------------------------------------------------
try:
    import numpy as np

    NUMPY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    NUMPY_AVAILABLE = False
    np = None  # type: ignore[assignment]

try:
    import pennylane as qml

    PENNYLANE_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    PENNYLANE_AVAILABLE = False
    qml = None  # type: ignore[assignment]

PENNYLANE_INSTALL_MESSAGE = (
    "ERROR: PennyLane is required for circuit construction/simulation "
    "(workflow prerequisite: pennylane >= 0.38).\n"
    "Install with:  pip install 'pennylane>=0.38' 'pennylane-lightning>=0.38' "
    "'numpy>=1.26'\n"
    "Resource accounting (qubit_count / gate_depth / resource_report) works "
    "without it, by design."
)

# Workflow Stage 2 step 2: readout sample counts at these precisions.
EPSILONS: tuple[float, ...] = (1e-1, 1e-2, 1e-3)


class HHLCaveatViolation(ValueError):
    """Raised when an input violates an HHL precondition (Aaronson caveats).

    Workflow Stage 2 requires caveat *enforcement*, not just documentation:
    non-Hermitian / non-sparse structure or condition number κ above a
    configurable bound must refuse to build a circuit (research doc §2.3,
    caveats 1–5; Aaronson, "Read the fine print", ref [4]).
    """


class MissingDependencyError(ImportError):
    """Raised when a circuit method needs an uninstalled quantum dependency."""


# --------------------------------------------------------------------------
# Shared accounting helpers (dependency-free, reused by Stage 3)
# --------------------------------------------------------------------------
def shots_for_precision(epsilon: float) -> int:
    """Classical/sampling shot count Θ(1/ε²) to resolve an expectation to ±ε.

    **[Proven]** for the standard measurement model (research doc §3.1, §4.2).
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    return math.ceil(1.0 / epsilon**2)


def qae_queries_for_precision(epsilon: float) -> int:
    """QAE oracle-call count O(1/ε) for the same ±ε target.

    **[Proven]** (Brassard et al., research doc §2.2 ref [2]) — quoted for
    comparison; QAE is *not* implemented in this module.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    return math.ceil(1.0 / epsilon)


def parameter_shift_executions(n_params: int) -> int:
    """Circuit executions for one full parameter-shift gradient: 2 per parameter.

    The O(d) executions-per-step economics that invert classical reverse-mode
    autodiff's O(1)-sweep amortization — **[Proven]** for the standard
    measurement model (research doc §3.1).
    """
    if n_params < 0:
        raise ValueError("n_params must be non-negative")
    return 2 * n_params


def amplitude_encoding_prep_cost(n_features: int) -> dict[str, int]:
    """Honest gate accounting for amplitude-encoding ``n_features`` values.

    Amplitude encoding packs 2^n arbitrary features into n qubits but requires
    O(2^n) gate depth in general — **[Proven]** (research doc §3.1; the §2.0
    input-cost wall in miniature). We count the standard multiplexed-rotation
    decomposition: ~2^(n+1) − 2 single-qubit rotations plus a comparable CNOT
    count, and report the gate count itself as a depth upper bound (no
    parallelism assumed — an over-, never under-statement).

    Returns ``{"n_qubits", "state_prep_gates", "prep_depth_upper_bound"}``.
    """
    if n_features < 1:
        raise ValueError("n_features must be >= 1")
    n_qubits = max(1, math.ceil(math.log2(n_features)))
    gates = 2 ** (n_qubits + 1) - 2
    return {
        "n_qubits": n_qubits,
        "state_prep_gates": gates,
        "prep_depth_upper_bound": gates,
    }


@dataclass
class ResourceReport:
    """One op's honest resource row (workflow Stage 2 step 2).

    Fields mirror the mandated table columns: logical qubits, two-qubit gate
    depth, state-prep gate count, and readout sample counts at
    ε ∈ {1e-1, 1e-2, 1e-3}. A report listing only a polylog "core" gate count
    fails Stage 2 review — state-prep and readout walls are always included
    (research doc §2.0, §4.4).
    """

    op_name: str
    logical_qubits: int
    two_qubit_gate_depth: int
    state_prep_gate_count: int
    readout_samples: dict[str, int]
    status_tag: str
    notes: list[str] = field(default_factory=list)

    def as_markdown_row(self) -> str:
        """Render as a markdown table row for quantum_attention_resources.md."""
        readout = "; ".join(f"ε={k}: {v:,}" for k, v in self.readout_samples.items())
        return (
            f"| {self.op_name} | {self.logical_qubits} | "
            f"{self.two_qubit_gate_depth:,} | {self.state_prep_gate_count:,} | "
            f"{readout} | {self.status_tag} |"
        )

    @staticmethod
    def markdown_header() -> str:
        """Markdown header matching :meth:`as_markdown_row`."""
        return (
            "| Op | Logical qubits | 2Q gate depth (upper bound) | "
            "State-prep gates | Readout samples | Status |\n"
            "|---|---|---|---|---|---|"
        )


# --------------------------------------------------------------------------
# Op 1 — HHL matrix-vector solve (quantum counterpart of the matmul ops)
# --------------------------------------------------------------------------
class HHLMatVec:
    """Toy-scale HHL linear solve |x⟩ ∝ A⁻¹|b⟩ for 2x2 / 4x4 Hermitian A.

    Quantum counterpart probed against the classical matmul-dominated ops
    (research doc §2.3, §4). The HHL complexity Õ(log N · s²κ²/ε) is
    **[Proven]** *as a quantum-state-output algorithm* (Harrow–Hassidim–Lloyd,
    research doc ref [3]); the output is a quantum state |x⟩, **not** the
    classical vector x — reading out all N entries costs Ω(N) tomography
    samples (Ω(N/ε²) at precision ε) **[Proven]** (research doc §2.3 caveat 2,
    §4.4), and end-to-end advantage for training workloads is
    **[Speculative]** after the five Aaronson caveats (ref [4]).

    Caveat enforcement (workflow Stage 2 acceptance — tested, not just
    documented): construction raises :class:`HHLCaveatViolation` when A is
    non-Hermitian, when κ exceeds ``kappa_bound`` (runtime scales as κ²,
    caveat 3 **[Proven]**), or when row sparsity exceeds ``sparsity_bound``
    (caveat 4 **[Proven]**). Caveats 1 (state preparation: O(N) without qRAM)
    and 2 (readout) are *counted* in :meth:`resource_report`; caveat 5
    (dequantization, Tang ref [5]) is recorded as a note.

    Simulated vs. real: :meth:`circuit` injects e^{iAt} as a dense
    ``QubitUnitary`` computed by classical eigendecomposition — legitimate
    only at toy scale on a statevector simulator. On hardware, Hamiltonian
    simulation of A is itself a nontrivial compiled circuit; our
    :meth:`gate_depth` reflects a generic dense-unitary decomposition bound,
    not this shortcut. Post-selection on the rotation ancilla is performed
    classically on the simulator statevector. The toy implementation further
    requires positive-definite A so eigenphases land in (0, 1) without a sign
    qubit (an implementation restriction, distinct from the Aaronson caveats).
    """

    def __init__(
        self,
        matrix: Sequence[Sequence[float]],
        b: Sequence[float],
        kappa_bound: float = 5.0,
        sparsity_bound: int | None = None,
        n_clock_qubits: int = 3,
    ) -> None:
        """Validate A against the HHL caveats and store the toy system.

        Args:
            matrix: Hermitian A, dimension 2 or 4 (workflow toy scale).
            b: right-hand-side vector, same dimension as A.
            kappa_bound: configurable κ ceiling (workflow validates fidelity
                >= 0.99 for κ <= 5, hence the default).
            sparsity_bound: max nonzeros per row; ``None`` permits dense rows
                at toy scale (caveat still *reported*).
            n_clock_qubits: QPE clock register size (eigenvalue precision).
        """
        if not NUMPY_AVAILABLE:
            raise MissingDependencyError(
                "numpy is required for HHL condition-number/caveat checks. "
                "Install with: pip install 'numpy>=1.26'"
            )
        self.matrix = np.asarray(matrix, dtype=complex)
        self.b = np.asarray(b, dtype=complex)
        self.kappa_bound = float(kappa_bound)
        self.n_clock_qubits = int(n_clock_qubits)

        dim = self.matrix.shape[0]
        if self.matrix.shape != (dim, dim) or dim not in (2, 4):
            raise ValueError(
                f"toy scale requires a 2x2 or 4x4 matrix, got {self.matrix.shape} "
                "(workflow Stage 2 step 1)"
            )
        if self.b.shape != (dim,):
            raise ValueError(f"b must have shape ({dim},), got {self.b.shape}")
        self.dim = dim
        self.n_system_qubits = int(math.log2(dim))
        self.sparsity_bound = dim if sparsity_bound is None else int(sparsity_bound)
        self._enforce_caveats()

    # -- caveat machinery ---------------------------------------------------
    @property
    def kappa(self) -> float:
        """Condition number κ = |λ|_max / |λ|_min of the Hermitian A."""
        eigvals = np.linalg.eigvalsh(self.matrix)
        magnitudes = np.abs(eigvals)
        if magnitudes.min() == 0:
            return math.inf
        return float(magnitudes.max() / magnitudes.min())

    @property
    def row_sparsity(self) -> int:
        """Max nonzeros per row, s (HHL runtime carries s² — caveat 4)."""
        return int(np.max(np.count_nonzero(self.matrix, axis=1)))

    def _enforce_caveats(self) -> None:
        """Raise :class:`HHLCaveatViolation` on any violated precondition."""
        if not np.allclose(self.matrix, self.matrix.conj().T):
            raise HHLCaveatViolation(
                "A is not Hermitian — HHL requires a Hermitian (or "
                "Hermitian-dilated) matrix (research doc §2.3)."
            )
        kappa = self.kappa
        if kappa > self.kappa_bound:
            raise HHLCaveatViolation(
                f"condition number κ={kappa:.3g} exceeds bound "
                f"{self.kappa_bound:.3g}: HHL runtime scales as κ² and "
                "ill-conditioned systems lose the advantage "
                "(Aaronson caveat 3, research doc §2.3 [Proven])."
            )
        if self.row_sparsity > self.sparsity_bound:
            raise HHLCaveatViolation(
                f"row sparsity s={self.row_sparsity} exceeds bound "
                f"{self.sparsity_bound}: A must be sparse or efficiently "
                "block-encodable (Aaronson caveat 4, research doc §2.3 [Proven])."
            )
        eigvals = np.linalg.eigvalsh(self.matrix)
        if np.min(eigvals) <= 0:
            raise ValueError(
                "toy HHL implementation requires positive-definite A "
                "(implementation restriction: eigenphases must land in (0,1) "
                "without a sign qubit; not one of the five Aaronson caveats)."
            )

    def caveat_notes(self) -> list[str]:
        """The five Aaronson caveats, each tagged, for the resource report."""
        return [
            "Caveat 1 — state prep: loading |b⟩ of N generic amplitudes costs "
            "Ω(N) gates without qRAM [Proven] (§2.3); counted in state-prep column.",
            f"Caveat 2 — readout: output is a quantum state; full classical "
            f"readout costs Ω(N/ε²) ≈ {self.dim}/ε² samples [Proven] (§2.3, §4.4); "
            "counted in readout column.",
            f"Caveat 3 — condition number: runtime ∝ κ²; enforced κ={self.kappa:.3g} "
            f"<= {self.kappa_bound:.3g} [Proven] (§2.3).",
            f"Caveat 4 — sparsity: enforced s={self.row_sparsity} <= "
            f"{self.sparsity_bound} [Proven] (§2.3).",
            "Caveat 5 — dequantization: low-rank + sampling access admits "
            "quantum-inspired classical algorithms (Tang, ref [5]) [Proven]; "
            "end-to-end advantage [Speculative].",
        ]

    # -- resource accounting (dependency-free) -------------------------------
    def qubit_count(self) -> int:
        """system (log2 N) + clock + 1 rotation ancilla (<= 8 at toy scale)."""
        return self.n_system_qubits + self.n_clock_qubits + 1

    def gate_depth(self) -> int:
        """Two-qubit gate-count upper bound for the full toy HHL pipeline.

        Serial gate count is reported as a depth upper bound (no parallelism
        assumed). Terms: |b⟩ amplitude prep O(2^n_sys) [Proven] §3.1; QPE with
        m controlled dense unitaries on n_sys qubits at a generic O(4^n_sys)
        two-qubit decomposition each (×4 control overhead); inverse QFT
        m(m−1)/2 controlled phases; (2^m − 1) multi-controlled eigenvalue
        rotations at ~2m two-qubit gates each; then QPE uncomputation.
        Heuristic constants, honest in direction (over-counting).
        """
        n_sys, m = self.n_system_qubits, self.n_clock_qubits
        prep = amplitude_encoding_prep_cost(self.dim)["state_prep_gates"]
        qpe_ctrl_u = m * (4**n_sys) * 4
        inv_qft = m * (m - 1) // 2
        eig_rotations = (2**m - 1) * 2 * m
        return prep + 2 * (qpe_ctrl_u + inv_qft) + eig_rotations

    def resource_report(self) -> ResourceReport:
        """Honest resource row including state-prep and readout walls."""
        return ResourceReport(
            op_name=f"HHLMatVec({self.dim}x{self.dim}, κ={self.kappa:.2f})",
            logical_qubits=self.qubit_count(),
            two_qubit_gate_depth=self.gate_depth(),
            state_prep_gate_count=amplitude_encoding_prep_cost(self.dim)[
                "state_prep_gates"
            ],
            readout_samples={
                f"{eps:.0e}": self.dim * shots_for_precision(eps) for eps in EPSILONS
            },
            status_tag=(
                "[Proven] state-output algorithm; end-to-end advantage "
                "[Speculative] (research doc §2.3, Table 1)"
            ),
            notes=self.caveat_notes(),
        )

    # -- simulation ----------------------------------------------------------
    def solve_classically(self) -> "np.ndarray":
        """Normalized classical solution x/||x|| for fidelity validation."""
        x = np.linalg.solve(self.matrix, self.b)
        return x / np.linalg.norm(x)

    def circuit(self) -> Callable[[], Any]:
        """Build the toy HHL QNode on ``default.qubit`` returning ``qml.state()``.

        Wire layout: clock [0..m-1] (MSB first, matching PennyLane's
        ``QuantumPhaseEstimation`` convention), system [m..m+n_sys-1],
        rotation ancilla last. e^{iAt₀} is injected as a dense QubitUnitary
        from the classical eigendecomposition (toy-scale shortcut — see class
        docstring). Requires PennyLane.
        """
        if not PENNYLANE_AVAILABLE:
            raise MissingDependencyError(PENNYLANE_INSTALL_MESSAGE)
        m, n_sys = self.n_clock_qubits, self.n_system_qubits
        clock = list(range(m))
        system = list(range(m, m + n_sys))
        ancilla = m + n_sys

        # Evolution time t0 scales the spectrum so phases φ = λ t0 / 2π ∈ (0,1).
        eigvals, eigvecs = np.linalg.eigh(self.matrix)
        lam_max = float(np.max(eigvals))
        t0 = 2 * math.pi * (1 - 2.0**-m) / lam_max
        unitary = eigvecs @ np.diag(np.exp(1j * eigvals * t0)) @ eigvecs.conj().T

        # Rotation constant C is set to the smallest QPE-representable
        # eigenvalue λ_unit = 2π/(t0·2^m), so C/λ̃_j = 1/j <= 1 for all j >= 1.
        b_norm = self.b / np.linalg.norm(self.b)

        dev = qml.device("default.qubit", wires=self.qubit_count())

        @qml.qnode(dev)
        def hhl_state() -> Any:
            qml.StatePrep(b_norm, wires=system)
            qml.QuantumPhaseEstimation(unitary, target_wires=system, estimation_wires=clock)
            # Eigenvalue-conditioned ancilla rotation: for each clock value j,
            # rotate by θ_j = 2 arcsin(C / λ̃_j) with λ̃_j = j·λ_unit and
            # C = λ_unit, giving θ_j = 2 arcsin(1/j).
            for j in range(1, 2**m):
                theta = 2 * math.asin(1.0 / j)
                bits = [int(bit) for bit in format(j, f"0{m}b")]
                qml.ctrl(qml.RY, control=clock, control_values=bits)(theta, wires=ancilla)
            qml.adjoint(qml.QuantumPhaseEstimation)(
                unitary, target_wires=system, estimation_wires=clock
            )
            return qml.state()

        return hhl_state

    def solve_quantum(self) -> "np.ndarray":
        """Run the circuit, post-select ancilla=1 classically, return |x̃⟩.

        The post-selection is a simulator-side convenience (class docstring);
        on hardware it is a repeat-until-success loop whose expected cost is
        folded into the κ-dependence of the [Proven] HHL bound.
        """
        state = np.asarray(self.circuit()())
        # Wire order [clock..., system..., ancilla]: index bits follow wire
        # order, so with clock uncomputed to |0...0⟩ the post-selected
        # amplitudes sit at index = system_value * 2 + 1.
        amps = np.array([state[s * 2 + 1] for s in range(self.dim)])
        norm = np.linalg.norm(amps)
        if norm == 0:
            raise RuntimeError("post-selection failed: zero ancilla=1 amplitude")
        return amps / norm

    def fidelity_vs_classical(self) -> float:
        """|⟨x_classical|x_quantum⟩|² — Stage 2 acceptance: >= 0.99 for κ <= 5."""
        return float(abs(np.vdot(self.solve_classically(), self.solve_quantum())) ** 2)


# --------------------------------------------------------------------------
# Op 2 — Quantum softmax approximation by amplitude-encoded sampling
# --------------------------------------------------------------------------
class QuantumSoftmaxSampler:
    """Softmax approximation: amplitude-encode √softmax(logits), then sample.

    Construction: the normalized exp-logits p_i = softmax(logits)_i are
    encoded as amplitudes √p_i on n = ⌈log₂ K⌉ qubits; computational-basis
    measurement then samples i with probability p_i, and an S-shot empirical
    histogram estimates the distribution. **[Theoretical]** as an estimation
    primitive (research doc §4.2): the output is an ε-*estimate*, not an
    exact softmax row, and the per-entry statistical error behaves like
    multiplicative noise on every matmul — much harsher than deterministic
    rounding, which is why end-to-end trainability through this op is
    **[Speculative]** and why workflow risk #8 keeps it out of Stage 3's
    training path.

    Honest input accounting: amplitude encoding of 2^n arbitrary values costs
    O(2^n) gate depth **[Proven]** (research doc §3.1) and is counted in
    :meth:`resource_report` — the "quantum softmax" never gets its inputs for
    free. Readout: resolving each entry to ±ε needs Θ(1/ε²) shots; QAE would
    improve this to O(1/ε) **[Proven]** (ref [2]) but is not implemented here.

    Simulated vs. real: sampling runs on ``default.qubit`` with finite shots;
    the simulator draws from the exact distribution, so measured TV distances
    reflect pure shot noise — exactly the statistical floor hardware would
    add *on top of* gate noise.
    """

    def __init__(self, logits: Sequence[float], default_shots: int = 10_000) -> None:
        """Store logits (length K >= 2) and the default shot budget S."""
        self.logits = [float(v) for v in logits]
        if len(self.logits) < 2:
            raise ValueError("need at least 2 logits")
        self.default_shots = int(default_shots)
        self.n_qubits = max(1, math.ceil(math.log2(len(self.logits))))
        self.padded_dim = 2**self.n_qubits

    def exact_softmax(self) -> list[float]:
        """Numerically stable exact softmax (pure Python, dependency-free)."""
        peak = max(self.logits)
        exps = [math.exp(v - peak) for v in self.logits]
        total = sum(exps)
        return [e / total for e in exps]

    # -- resource accounting (dependency-free) -------------------------------
    def qubit_count(self) -> int:
        """n = ⌈log₂ K⌉ qubits for K logits (padded to 2^n)."""
        return self.n_qubits

    def gate_depth(self) -> int:
        """State-prep dominated: O(2^n) amplitude-encoding depth [Proven] §3.1."""
        return amplitude_encoding_prep_cost(self.padded_dim)["prep_depth_upper_bound"]

    def resource_report(self) -> ResourceReport:
        """Resource row; readout column is per-entry Θ(1/ε²) shot counts."""
        prep = amplitude_encoding_prep_cost(self.padded_dim)
        return ResourceReport(
            op_name=f"QuantumSoftmaxSampler(K={len(self.logits)})",
            logical_qubits=self.qubit_count(),
            two_qubit_gate_depth=self.gate_depth(),
            state_prep_gate_count=prep["state_prep_gates"],
            readout_samples={
                f"{eps:.0e}": shots_for_precision(eps) for eps in EPSILONS
            },
            status_tag=(
                "[Theoretical] estimation primitive; end-to-end advantage "
                "[Speculative] (research doc §4.2, Table 2)"
            ),
            notes=[
                "State prep of 2^n arbitrary amplitudes costs O(2^n) depth "
                "[Proven] (§3.1) — included above, never treated as free.",
                "Readout column is per-entry; a full K-entry distribution at "
                "±ε costs ~K/ε² shots [Proven] sampling bound (§4.2).",
                f"QAE alternative: O(1/ε) queries [Proven] [2] — e.g. "
                f"{qae_queries_for_precision(1e-2):,} vs "
                f"{shots_for_precision(1e-2):,} at ε=1e-2; not implemented here.",
                "Per-entry statistical error ~ multiplicative noise on every "
                "matmul — harsher than deterministic rounding (§4.2); excluded "
                "from Stage 3's training path (workflow risk #8).",
            ],
        )

    # -- simulation ----------------------------------------------------------
    def circuit(self, shots: int | None = None) -> Callable[[], Any]:
        """QNode returning S-shot empirical probabilities (requires PennyLane)."""
        if not PENNYLANE_AVAILABLE:
            raise MissingDependencyError(PENNYLANE_INSTALL_MESSAGE)
        probs = self.exact_softmax()
        amps = [math.sqrt(p) for p in probs] + [0.0] * (self.padded_dim - len(probs))
        dev = qml.device(
            "default.qubit", wires=self.n_qubits, shots=shots or self.default_shots
        )

        @qml.qnode(dev)
        def sample_softmax() -> Any:
            qml.StatePrep(amps, wires=range(self.n_qubits), normalize=True)
            return qml.probs(wires=range(self.n_qubits))

        return sample_softmax

    def estimate(self, shots: int | None = None) -> list[float]:
        """S-shot empirical estimate of the softmax distribution (length K)."""
        raw = self.circuit(shots)()
        return [float(v) for v in raw][: len(self.logits)]

    @staticmethod
    def tv_distance(p: Sequence[float], q: Sequence[float]) -> float:
        """Total-variation distance ½ Σ|p_i − q_i|."""
        return 0.5 * sum(abs(a - b) for a, b in zip(p, q, strict=True))

    def tv_distance_vs_shots(
        self, shot_schedule: Sequence[int] = (100, 1_000, 10_000)
    ) -> dict[int, float]:
        """TV distance to the exact softmax as a function of shot count S.

        Workflow Stage 2 acceptance: TV <= 0.05 at S = 10⁴ shots.
        """
        exact = self.exact_softmax()
        return {
            int(s): self.tv_distance(exact, self.estimate(int(s)))
            for s in shot_schedule
        }


# --------------------------------------------------------------------------
# Op 3 — Parameter-shift gradient estimation for a small VQC
# --------------------------------------------------------------------------
class ParameterShiftGradient:
    """Parameter-shift gradients for a 4–8 qubit, 2–3 layer VQC, local cost.

    The quantum counterpart of the profiled classical ``grad_update`` op.
    Ansatz: per layer, one RY rotation per qubit followed by a ring of CNOTs;
    cost function C(θ) = ⟨Z₀⟩ — a **local** observable, chosen per Cerezo et
    al. (research doc §3.3–3.4 [Proven]) so gradients vanish only polynomially
    at depth O(log n), staying clear of barren plateaus (random deep circuits
    with *global* costs have Var[∂C/∂θ] ∈ O(2⁻ⁿ) [Proven], McClean et al.).

    Gradient access uses the exact parameter-shift rule **[Proven]**
    (research doc §3.1):

        ∂C/∂θ_k = ½ [ C(θ_k + π/2) − C(θ_k − π/2) ]

    Inverted economics, counted not asserted: :meth:`gradient` issues the two
    shifted executions per parameter itself and tallies them in
    ``self.executions_last_gradient`` — O(d) circuit executions per gradient
    step, each needing O(1/ε²) shots to resolve the expectation to ±ε, versus
    classical reverse-mode's O(1)-sweep for all d derivatives **[Proven]**
    (§3.1). Adjoint differentiation reproduces the O(1) sweep *only on
    classical simulators*, never on hardware (§3.1).

    Simulated vs. real: runs on ``default.qubit`` (analytic or shot-based).
    Analytic mode has zero estimator variance and exists only in simulation;
    shot mode reproduces the statistical economics hardware would have,
    without hardware gate noise.
    """

    MIN_QUBITS, MAX_QUBITS = 4, 8  # workflow Stage 2 step 1 range
    MIN_LAYERS, MAX_LAYERS = 2, 3

    def __init__(
        self, n_qubits: int = 4, n_layers: int = 2, shots: int | None = None
    ) -> None:
        """Validate the workflow's size envelope and store the ansatz shape."""
        if not (self.MIN_QUBITS <= n_qubits <= self.MAX_QUBITS):
            raise ValueError(
                f"n_qubits must be in [{self.MIN_QUBITS}, {self.MAX_QUBITS}] "
                "(workflow Stage 2 step 1)"
            )
        if not (self.MIN_LAYERS <= n_layers <= self.MAX_LAYERS):
            raise ValueError(
                f"n_layers must be in [{self.MIN_LAYERS}, {self.MAX_LAYERS}] "
                "(workflow Stage 2 step 1)"
            )
        self.n_qubits = n_qubits
        self.n_layers = n_layers
        self.shots = shots
        self.n_params = n_qubits * n_layers  # one RY per qubit per layer
        self.executions_last_gradient: int = 0

    # -- resource accounting (dependency-free) -------------------------------
    def qubit_count(self) -> int:
        """Qubits in the VQC."""
        return self.n_qubits

    def gate_depth(self) -> int:
        """Two-qubit depth bound: one CNOT ring (n gates) per layer."""
        return self.n_layers * self.n_qubits

    def executions_per_step(self) -> int:
        """Circuit executions for one full gradient: 2d (parameter-shift)."""
        return parameter_shift_executions(self.n_params)

    def resource_report(self) -> ResourceReport:
        """Resource row; readout column is shots *per expectation value*."""
        return ResourceReport(
            op_name=(
                f"ParameterShiftGradient({self.n_qubits}q x {self.n_layers}L, "
                f"d={self.n_params})"
            ),
            logical_qubits=self.qubit_count(),
            two_qubit_gate_depth=self.gate_depth(),
            state_prep_gate_count=0,  # parameters are rotations, no data load
            readout_samples={
                f"{eps:.0e}": shots_for_precision(eps) for eps in EPSILONS
            },
            status_tag=(
                "[Proven] parameter-shift rule and O(d/ε²) hardware economics "
                "(research doc §3.1)"
            ),
            notes=[
                f"O(d) executions per gradient step: 2d = "
                f"{self.executions_per_step()} here [Proven] (§3.1).",
                "Full gradient at ±ε per component: 2d/ε² total shots — e.g. "
                f"{self.executions_per_step() * shots_for_precision(1e-2):,} "
                "at ε=1e-2 [Proven] (§3.1).",
                "Local cost ⟨Z₀⟩, depth O(log n): trainable regime per Cerezo "
                "et al. [Proven] (§3.3–3.4).",
                "No state-prep column cost: this op loads parameters, not data.",
            ],
        )

    # -- simulation ----------------------------------------------------------
    def circuit(self) -> Callable[[Sequence[float]], float]:
        """QNode C(θ): layered RY + CNOT-ring ansatz, ⟨Z₀⟩ readout."""
        if not PENNYLANE_AVAILABLE:
            raise MissingDependencyError(PENNYLANE_INSTALL_MESSAGE)
        dev = qml.device("default.qubit", wires=self.n_qubits, shots=self.shots)

        @qml.qnode(dev)
        def cost(params: Sequence[float]) -> Any:
            for layer in range(self.n_layers):
                for wire in range(self.n_qubits):
                    qml.RY(params[layer * self.n_qubits + wire], wires=wire)
                for wire in range(self.n_qubits):
                    qml.CNOT(wires=[wire, (wire + 1) % self.n_qubits])
            return qml.expval(qml.PauliZ(0))  # LOCAL cost (Cerezo et al. [9])

        return cost

    def gradient(self, params: Sequence[float]) -> list[float]:
        """Exact parameter-shift gradient, counting every circuit execution.

        Implements ∂C/∂θ_k = ½[C(θ_k+π/2) − C(θ_k−π/2)] [Proven] (§3.1) by
        explicit shifted executions (2 per parameter) so the O(d) count is
        measured, not asserted; the tally lands in
        ``self.executions_last_gradient``.
        """
        params = [float(p) for p in params]
        if len(params) != self.n_params:
            raise ValueError(f"expected {self.n_params} parameters, got {len(params)}")
        cost = self.circuit()
        grad: list[float] = []
        executions = 0
        for k in range(self.n_params):
            plus = list(params)
            minus = list(params)
            plus[k] += math.pi / 2
            minus[k] -= math.pi / 2
            grad.append(0.5 * (float(cost(plus)) - float(cost(minus))))
            executions += 2
        self.executions_last_gradient = executions
        return grad


# --------------------------------------------------------------------------
# Demo / dry-run entry point
# --------------------------------------------------------------------------
def print_resource_reports() -> None:
    """Print the dependency-free resource table for all three ops."""
    print(ResourceReport.markdown_header())
    reports: list[ResourceReport] = []
    if NUMPY_AVAILABLE:
        reports.append(
            HHLMatVec([[1.5, 0.5], [0.5, 1.5]], [1.0, 0.0]).resource_report()
        )
    else:
        print("| HHLMatVec | (skipped: numpy not installed) | | | | |")
    reports.append(QuantumSoftmaxSampler([1.0, 2.0, 0.5, -1.0]).resource_report())
    reports.append(ParameterShiftGradient(n_qubits=4, n_layers=2).resource_report())
    for report in reports:
        print(report.as_markdown_row())
    print()
    for report in reports:
        print(f"{report.op_name}:")
        for note in report.notes:
            print(f"  - {note}")


def _run_demos() -> None:
    """Simulate all three ops on default.qubit and print validation metrics."""
    print("\n[demo 1] HHLMatVec — 2x2 well-conditioned system (κ=3)")
    hhl = HHLMatVec([[2.0, 1.0], [1.0, 2.0]], [1.0, 0.0])
    fidelity = hhl.fidelity_vs_classical()
    print(f"  fidelity vs classical solve: {fidelity:.4f} "
          "(Stage 2 acceptance: >= 0.99 for κ <= 5)")

    print("[demo 1b] caveat enforcement — ill-conditioned input must refuse")
    try:
        HHLMatVec([[1.0, 0.0], [0.0, 1e-3]], [1.0, 1.0])
    except HHLCaveatViolation as exc:
        print(f"  HHLCaveatViolation raised as required: {exc}")

    print("\n[demo 2] QuantumSoftmaxSampler — TV distance vs shots")
    sampler = QuantumSoftmaxSampler([1.0, 2.0, 0.5, -1.0, 0.0, 3.0])
    for shots, tv in sampler.tv_distance_vs_shots().items():
        print(f"  S={shots:>6d}  TV={tv:.4f}"
              + ("  (acceptance: <= 0.05)" if shots == 10_000 else ""))

    print("\n[demo 3] ParameterShiftGradient — analytic gradient + execution count")
    psg = ParameterShiftGradient(n_qubits=4, n_layers=2)
    params = [0.1 * (k + 1) for k in range(psg.n_params)]
    grad = psg.gradient(params)
    print(f"  d={psg.n_params} params -> {psg.executions_last_gradient} circuit "
          f"executions (2d, O(d) economics per research doc §3.1)")
    print(f"  grad[:4] = {[round(g, 4) for g in grad[:4]]}")


def main(argv: list[str] | None = None) -> int:
    """Print resource accounting; run simulator demos if PennyLane is present."""
    parser = argparse.ArgumentParser(
        description=(
            "Stage 2 quantum circuit equivalents "
            "(docs/workflows/01-qml-workflow.md)."
        )
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print the dependency-free resource reports and exit",
    )
    args = parser.parse_args(argv)

    print("[stage-2] resource accounting (dependency-free, honest I/O walls):\n")
    print_resource_reports()
    if args.report_only:
        return 0
    if not PENNYLANE_AVAILABLE:
        sys.stdout.flush()  # keep report/error ordering sane when piped
        print(PENNYLANE_INSTALL_MESSAGE, file=sys.stderr)
        return 1
    _run_demos()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
