"""Op-by-op quantum-vs-classical complexity comparison and crossover analysis.

Workflow Stage 4 deliverable for the ``qml-accelerator`` sub-project
(see ``docs/workflows/01-qml-workflow.md``, Stage 4). This script encodes the
cost models of the research document ``docs/research/01-qml-accelerator.md``
(Tables 1-3, Sections 2.0, 4.4, 6, 7.1) as a declarative ``OPS`` table, finds
the batch-size / precision / dimension crossover points (or, honestly, shows
that none exists in any realistic range), and renders:

* a Markdown complexity table (``complexity_table.md``), column-compatible
  with research doc Tables 1-3;
* two chart families (``figures/speedup_query_model.png`` and
  ``figures/crossover_wall_clock.png``).

Epistemic convention (inherited from the research doc): every quantitative
claim carries one of **[Proven]**, **[Demonstrated]**, **[Theoretical]**,
**[Speculative]**. The headline finding reproduced here is the research doc's
honest conclusion: under the Section 2.0 translation losses (oracle-synthesis
constants of 10^2-10^4, a logical-clock deficit of 10^8-10^10x, and
Omega(n/eps^2) readout where classical output is required), **no realistic
crossover exists** for the gradient-estimation op, and the matvec/linear-solve
crossover survives only in the state-output-only framing whose caveats
(Aaronson [4]) erase the practical advantage.

Framing note (workflow Stage 4, step 4): the matvec row's classical baseline
here is the dense matvec *op* at O(n^2), whereas research doc Table 1 frames
HHL against conjugate gradient at O(N*s*kappa) -- a linear *solve* to a state
vector. Both are correct in their own framing; the emitted table carries an
explicit annotation on that row so a mechanical Table 1 comparison does not
flag a false mismatch.

Dependency policy: ``matplotlib`` is imported *only* inside the plotting
functions, so ``--table-only`` (and ``py_compile``) work in environments where
matplotlib is not installed. The core cost models use only the standard
library.

Usage::

    python complexity_analysis.py                 # tables + figures
    python complexity_analysis.py --table-only    # text tables, no matplotlib
    python complexity_analysis.py --out-dir /tmp  # redirect outputs
    python complexity_analysis.py --verify        # assert cost-model strings
                                                  # match the research doc
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Constants from the research doc (every one cited; none invented here).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostConstants:
    """Explicit constant factors from the research doc.

    Each field cites the section of ``docs/research/01-qml-accelerator.md``
    that derives it. Per the workflow ground rules, anything the research doc
    marks [Speculative] is a *labeled assumption with a tunable constant* --
    never silently treated as free.
    """

    # Section 2.0(1): reversible oracle compilation inflates cost by
    # constants of 10^2-10^4. [Theoretical]
    oracle_synthesis_low: float = 1e2
    oracle_synthesis_high: float = 1e4

    # Section 2.0(3) / 7.1(2): fault-tolerant logical gate rate, projected
    # 10^4-10^6 ops/s. [Theoretical] logical-rate extrapolation over
    # [Demonstrated] ~1 us physical cycles (Willow [24]).
    logical_rate_low: float = 1e4
    logical_rate_high: float = 1e6

    # Section 7.1(1): A100 at ~45-50% MFU -> ~1.5e14 effective FLOP/s. [23]
    classical_rate: float = 1.5e14

    # Section 6.5(1): one attention layer of a 1B-parameter model has
    # d = 3*d_model^2 ~ 10^7-10^8 trainable parameters.
    d_params: float = 1e7

    # Section 7.1(4): per-example forward+backward cost for a single
    # attention-layer subroutine, C_f ~ 10^9 ops.
    c_f: float = 1e9

    # Section 6.5(2): the honest classical baseline is minibatch SGD with
    # B = O(1)-O(10^3); we use a representative B.
    sgd_batch: float = 64.0

    # HHL parameters (Section 2.3): row sparsity s and condition number
    # kappa for a *favourable* toy regime (the advantage degrades as
    # kappa^2 for ill-conditioned curvature matrices). [Proven] scaling.
    sparsity: float = 2.0
    kappa: float = 5.0

    # Target additive precision for estimation primitives (Sections 2.2,
    # 4.2). Readout of classical output costs Omega(n/eps^2). [Proven]
    epsilon: float = 1e-2

    @property
    def clock_deficit_low(self) -> float:
        """Best-case clock deficit: classical_rate / logical_rate_high.

        Section 2.0(3): 'a ~10^8-10^10x constant'. This is the 10^8 end.
        """
        return self.classical_rate / self.logical_rate_high

    @property
    def clock_deficit_high(self) -> float:
        """Worst-case clock deficit (the 10^10 end of Section 2.0(3))."""
        return self.classical_rate / self.logical_rate_low


# ---------------------------------------------------------------------------
# Declarative OPS table (workflow Stage 4, step 1).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpModel:
    """One profiled op with its classical and quantum cost models.

    ``classical_cost`` and ``quantum_cost`` map the op's natural scale
    variable (n, 1/eps, or N -- see ``scale_label``) to abstract operation
    counts in the *query/gate* model; wall-clock translation is applied
    separately so the two chart families stay honestly distinguished
    (research doc Section 2.0).
    """

    key: str
    name: str
    scale_label: str
    classical_expr: str
    quantum_expr: str
    classical_cost: Callable[[float, CostConstants], float]
    quantum_cost: Callable[[float, CostConstants], float]
    preconditions: str
    output_form: str
    status: str
    doc_section: str
    framing_note: str = ""
    crossover_caveat: str = ""
    extra_curves: dict[str, Callable[[float, CostConstants], float]] = field(
        default_factory=dict
    )


def _matvec_classical(n: float, _c: CostConstants) -> float:
    """Dense matvec: O(n^2) multiply-adds (framing note: *op*, not solve)."""
    return n * n


def _matvec_cg_solve(n: float, c: CostConstants) -> float:
    """Conjugate-gradient linear solve to a state vector: O(N*s*kappa).

    This is research doc Table 1's classical baseline for HHL -- a *solve*,
    not a matvec. Kept as an extra curve so both framings are visible.
    """
    return n * c.sparsity * c.kappa


def _matvec_hhl_state_only(n: float, c: CostConstants) -> float:
    """HHL core gate count, state output only: O~(log N * s^2 kappa^2 / eps).

    Research doc Section 2.3 [Proven] as a quantum-state-output algorithm.
    Excludes the O(n^2) block-encoding/qRAM build (Section 4.4(1)) and all
    readout -- i.e., the most charitable possible accounting.
    """
    return math.log2(max(n, 2.0)) * c.sparsity**2 * c.kappa**2 / c.epsilon


def _matvec_hhl_classical_readout(n: float, c: CostConstants) -> float:
    """HHL with full classical readout: Omega(n/eps^2) tomography repetitions.

    Research doc Sections 2.3 caveat 2 and 4.4(2) [Proven]: reading the
    N-dimensional answer out costs Omega(n/eps^2) samples, each requiring a
    fresh run of the core circuit. This erases the log-n advantage.
    """
    repetitions = n / c.epsilon**2
    return repetitions * _matvec_hhl_state_only(n, c)


def _mean_classical(inv_eps: float, _c: CostConstants) -> float:
    """Classical Monte Carlo mean estimation: Theta(1/eps^2) samples."""
    return inv_eps**2


def _mean_qae(inv_eps: float, _c: CostConstants) -> float:
    """QAE: O(1/eps) coherent applications of the sampler A (research doc
    Section 2.2, [Proven], Brassard et al. [2])."""
    return inv_eps


def _grad_classical_full_batch(n_batch: float, c: CostConstants) -> float:
    """Classical full-batch backprop: O(N * C_f), *all d components at once*
    via reverse mode (research doc Section 6.1, [Proven])."""
    return n_batch * c.c_f


def _grad_classical_sgd(_n_batch: float, c: CostConstants) -> float:
    """Classical minibatch SGD: O(B * C_f), B = O(1)-O(10^3) -- flat in N.

    Research doc Section 6.5(2): this, not full-batch GD, is the honest
    classical baseline. [Theoretical] objection, well-founded.
    """
    return c.sgd_batch * c.c_f


def _grad_quantum_qge(n_batch: float, c: CostConstants) -> float:
    """QGE-ATTN per the Section 6 sketch: O(d * sqrt(N) * O~(C_f)).

    One QAE per component -- there is no all-components trick (research doc
    Table 3). Query-model count; oracle-synthesis constants are applied only
    in the wall-clock translation, keeping the two framings separate.
    """
    return c.d_params * math.sqrt(n_batch) * c.c_f


OPS: dict[str, OpModel] = {
    "matvec": OpModel(
        key="matvec",
        name="Matvec / linear solve (HHL)",
        scale_label="matrix dimension n",
        classical_expr="O(n^2) dense matvec [framing: op, not solve]",
        quantum_expr="O~(log N * s^2 kappa^2 / eps), state output only",
        classical_cost=_matvec_classical,
        quantum_cost=_matvec_hhl_state_only,
        preconditions=(
            "qRAM/state prep, sparse A, low kappa, global-property readout "
            "(all five Aaronson caveats [4])"
        ),
        output_form="Quantum state only; classical readout costs Omega(n/eps^2)",
        status="[Proven] with caveats; end-to-end advantage [Speculative]",
        doc_section="research doc Sections 2.3, 4.4; Tables 1-2",
        framing_note=(
            "FRAMING (workflow Stage 4, step 4): classical baseline here is "
            "the dense matvec *op* at O(n^2); research doc Table 1 frames HHL "
            "against conjugate gradient at O(N*s*kappa) -- a linear *solve* "
            "to a state vector. Both are correct in their own framing; do "
            "not flag this as a Table 1 mismatch."
        ),
        crossover_caveat=(
            "state-output-only framing: excludes the Omega(n^2) qRAM/"
            "data-structure build (Section 4.4(1)) and the Omega(n/eps^2) "
            "classical readout (Section 4.4(2)), either of which erases the "
            "crossover; see the wall-clock figure's HHL+readout curve"
        ),
        extra_curves={
            "Classical CG solve O(N*s*kappa) [Table 1 framing]": _matvec_cg_solve,
            "HHL + Omega(n/eps^2) classical readout": _matvec_hhl_classical_readout,
        },
    ),
    "softmax_sampling": OpModel(
        key="softmax_sampling",
        name="Softmax / sampling (mean estimation)",
        scale_label="inverse precision 1/eps",
        classical_expr="Theta(1/eps^2) samples (Monte Carlo)",
        quantum_expr="O(1/eps) coherent calls (QAE)",
        classical_cost=_mean_classical,
        quantum_cost=_mean_qae,
        preconditions=(
            "Coherent sampler A; per-quantity readout; amplitude encoding of "
            "2^n arbitrary values costs O(2^n) gate depth [Proven, "
            "Section 3.1]"
        ),
        output_form=(
            "eps-additive estimate per entry; behaves like multiplicative "
            "noise on every matmul (Section 4.2)"
        ),
        status="[Proven] primitive; end-to-end advantage [Speculative]",
        doc_section="research doc Sections 2.2, 4.2; Tables 1-2",
        crossover_caveat=(
            "no training regime needs this precision -- A4 sets "
            "eps = Theta(G/sqrt(N)), and SGD thrives on noisy O(1)-sample "
            "estimates (Section 2.2)"
        ),
    ),
    "gradient": OpModel(
        key="gradient",
        name="Gradient estimation (one attention layer)",
        scale_label="batch size N",
        classical_expr="O(N * C_f) full-batch / O(B * C_f) SGD",
        quantum_expr="O(d * sqrt(N) * O~(C_f)) -- one QAE per component",
        classical_cost=_grad_classical_full_batch,
        quantum_cost=_grad_quantum_qge,
        preconditions="Assumptions A1-A4 of the Section 6 sketch",
        output_form=(
            "Per-component additive error G/sqrt(N); no all-components trick "
            "(classical reverse mode gets all d in one pass)"
        ),
        status="[Theoretical] accounting; [Speculative] hardware (A1, A2)",
        doc_section="research doc Section 6; Table 3",
        extra_curves={
            "Classical minibatch SGD O(B*C_f) [honest baseline, "
            "Section 6.5(2)]": _grad_classical_sgd,
        },
    ),
}


# Hard-coded expected complexity strings for --verify (workflow Stage 4,
# step 5). The matvec entry deliberately encodes the framing difference
# rather than asserting an exact Table 1 match.
EXPECTED_COMPLEXITIES: dict[str, tuple[str, str]] = {
    "matvec": (
        "O(n^2) dense matvec [framing: op, not solve]",
        "O~(log N * s^2 kappa^2 / eps), state output only",
    ),
    "softmax_sampling": (
        "Theta(1/eps^2) samples (Monte Carlo)",
        "O(1/eps) coherent calls (QAE)",
    ),
    "gradient": (
        "O(N * C_f) full-batch / O(B * C_f) SGD",
        "O(d * sqrt(N) * O~(C_f)) -- one QAE per component",
    ),
}

# Largest scale value treated as "realistic" for the gradient op: research
# doc Section 6.5(1) -- crossover needs N >> 10^14-10^16, and "no training
# corpus or batch regime looks like this".
REALISTIC_N_CEILING: float = 1e14


# ---------------------------------------------------------------------------
# Wall-clock translation and crossover search (workflow Stage 4, step 2).
# ---------------------------------------------------------------------------


def quantum_wall_clock(
    op_count: float, constants: CostConstants, *, best_case: bool
) -> float:
    """Translate a quantum query/gate count into seconds.

    Applies the two Section 2.0 translation losses that are constants:
    oracle-synthesis inflation (10^2-10^4, [Theoretical]) and the logical
    clock rate (10^4-10^6 ops/s, [Theoretical] extrapolation). ``best_case``
    selects the most quantum-favourable end of both ranges.
    """
    if best_case:
        return op_count * constants.oracle_synthesis_low / constants.logical_rate_high
    return op_count * constants.oracle_synthesis_high / constants.logical_rate_low


def classical_wall_clock(op_count: float, constants: CostConstants) -> float:
    """Translate a classical FLOP count into seconds on an A100 at ~50% MFU
    (research doc Section 7.1(1), ~1.5e14 effective FLOP/s [23])."""
    return op_count / constants.classical_rate


@dataclass(frozen=True)
class CrossoverResult:
    """Outcome of a crossover search for one op under one scenario."""

    op_key: str
    scenario: str
    crossover_scale: float | None
    realistic: bool
    note: str


def _log_grid(lo: float, hi: float, points_per_decade: int = 8) -> list[float]:
    """Logarithmically spaced grid from ``lo`` to ``hi`` (standard library
    only, so --table-only never needs numpy)."""
    n_points = max(2, int(math.log10(hi / lo) * points_per_decade))
    ratio = (hi / lo) ** (1.0 / (n_points - 1))
    return [lo * ratio**i for i in range(n_points)]


def crossover(
    op: OpModel,
    constants: CostConstants,
    *,
    best_case: bool = True,
    scale_lo: float = 1e1,
    scale_hi: float = 1e40,
) -> CrossoverResult:
    """Find the scale at which the quantum wall-clock model undercuts the
    classical one, or report that none exists up to ``scale_hi``.

    The search is over the op's natural scale variable (n, 1/eps, or N) on a
    log grid; the printed constants make every assumption explicit (workflow
    Stage 4, step 2). Per the workflow, axes/search ranges extend far enough
    to make a missing crossover visible rather than cropping to flatter a
    curve.
    """
    scenario = "best-case constants" if best_case else "worst-case constants"
    for scale in _log_grid(scale_lo, scale_hi):
        q_sec = quantum_wall_clock(
            op.quantum_cost(scale, constants), constants, best_case=best_case
        )
        c_sec = classical_wall_clock(op.classical_cost(scale, constants), constants)
        if q_sec < c_sec:
            realistic = scale <= REALISTIC_N_CEILING
            note = (
                "within plotted/realistic range"
                if realistic
                else (
                    f"crossover exists only beyond the realistic ceiling "
                    f"{REALISTIC_N_CEILING:.0e} -- effectively none "
                    f"(research doc Section 6.5)"
                )
            )
            return CrossoverResult(op.key, scenario, scale, realistic, note)
    return CrossoverResult(
        op.key,
        scenario,
        None,
        False,
        f"no crossover found up to {scale_hi:.0e} -- the research doc's "
        f"honest conclusion",
    )


def gradient_crossover_closed_form(
    constants: CostConstants, *, best_case: bool = True
) -> float:
    """Closed-form wall-clock crossover N for the gradient op.

    Setting d*sqrt(N)*c_or*C_f/R_q = N*C_f/R_c gives
    N = (d * c_or * R_c/R_q)^2. With d = 10^7, c_or = 10^2 and the 10^8
    clock deficit this is ~10^34 -- dwarfing even the query-model bound
    N > d^2 = 10^14 of research doc Section 6.5(1). [Proven] arithmetic.
    """
    if best_case:
        c_or = constants.oracle_synthesis_low
        deficit = constants.clock_deficit_low
    else:
        c_or = constants.oracle_synthesis_high
        deficit = constants.clock_deficit_high
    return (constants.d_params * c_or * deficit) ** 2


# ---------------------------------------------------------------------------
# Table rendering (workflow Stage 4, step 4).
# ---------------------------------------------------------------------------


def render_complexity_table(constants: CostConstants) -> str:
    """Render the op-by-op Markdown table, column-compatible with research
    doc Tables 1-3, including crossover findings and the framing note."""
    lines: list[str] = [
        "# Complexity Comparison Table -- qml-accelerator Stage 4",
        "",
        "Generated by `benchmarks/complexity_analysis.py`. Cost models are",
        "transcribed from `docs/research/01-qml-accelerator.md` Tables 1-3;",
        "wall-clock columns apply the Section 2.0 translation losses with the",
        "explicit constants printed below. **[Theoretical]** accounting",
        "throughout; the underlying arithmetic is **[Proven]** given the",
        "stated inputs.",
        "",
        "## Constants applied (all cited)",
        "",
        f"- Oracle-synthesis overhead: {constants.oracle_synthesis_low:.0e}-"
        f"{constants.oracle_synthesis_high:.0e} (**[Theoretical]**, Section 2.0(1))",
        f"- Logical clock rate: {constants.logical_rate_low:.0e}-"
        f"{constants.logical_rate_high:.0e} ops/s vs. classical "
        f"{constants.classical_rate:.1e} FLOP/s effective on an A100 "
        f"(Section 7.1) -> clock deficit {constants.clock_deficit_low:.0e}-"
        f"{constants.clock_deficit_high:.0e}x (**[Demonstrated]** physical "
        f"cycle times, **[Theoretical]** logical-rate extrapolation, "
        f"**[Proven]** consequence)",
        f"- Readout where classical output is required: Omega(n/eps^2) at "
        f"eps = {constants.epsilon:.0e} (**[Proven]**, Section 4.4(2))",
        f"- d = {constants.d_params:.0e} (one attention layer, 1B-parameter "
        f"model, Section 6.5(1)); C_f = {constants.c_f:.0e} ops (Section "
        f"7.1(4)); SGD batch B = {constants.sgd_batch:.0f} (Section 6.5(2))",
        "",
        "## Op-by-op comparison",
        "",
        "| Op | O(classical) | O(quantum) | Preconditions | Output form | "
        "Status |",
        "|---|---|---|---|---|---|",
    ]
    for op in OPS.values():
        lines.append(
            f"| {op.name} | {op.classical_expr} | {op.quantum_expr} | "
            f"{op.preconditions} | {op.output_form} | {op.status} |"
        )
    lines += ["", "## Crossover findings", ""]
    for op in OPS.values():
        for best in (True, False):
            res = crossover(op, constants, best_case=best)
            point = (
                f"{op.scale_label} ~ {res.crossover_scale:.1e}"
                if res.crossover_scale is not None
                else "none"
            )
            caveat = f" Caveat: {op.crossover_caveat}." if op.crossover_caveat else ""
            lines.append(
                f"- **{op.name}** ({res.scenario}): {point} -- {res.note}.{caveat}"
            )
    n_query = constants.d_params**2
    n_wall = gradient_crossover_closed_form(constants, best_case=True)
    lines += [
        "",
        "## Gradient-step closed form (Section 6.5(1), [Proven] arithmetic)",
        "",
        f"- Query-model crossover requires d << sqrt(N), i.e. N > d^2 = "
        f"{n_query:.0e}; the research doc states N >> 10^14-10^16 for "
        f"d ~ 10^7-10^8. No training corpus or batch regime looks like this.",
        f"- Wall-clock crossover (best-case constants): N > "
        f"(d * c_or * clock-deficit)^2 ~ {n_wall:.0e}. "
        f"**No realistic crossover exists.**",
        "",
        "## Framing notes",
        "",
    ]
    for op in OPS.values():
        if op.framing_note:
            lines.append(f"- {op.framing_note}")
    lines += [
        "",
        "Honest-baseline note: the gradient row's full-batch classical "
        "baseline is the *favourable-to-quantum* comparison; the honest "
        "classical baseline is minibatch SGD at O(B * C_f), flat in N "
        "(Section 6.5(2)) -- against it the quantum curve never wins at any "
        "N. **[Theoretical]** objection, well-founded.",
        "",
        "Simulator ground rule: nothing here measures hardware behaviour; "
        "these are cost-model projections, never simulator wall-clock "
        "plotted as hardware performance (workflow ground rules).",
        "",
    ]
    return "\n".join(lines)


def verify_cost_models() -> list[str]:
    """Assert the OPS table's symbolic cost strings match the research doc
    (workflow Stage 4, step 5). Returns a list of mismatch descriptions;
    empty means verified."""
    errors: list[str] = []
    for key, (expected_classical, expected_quantum) in EXPECTED_COMPLEXITIES.items():
        op = OPS.get(key)
        if op is None:
            errors.append(f"missing op '{key}' in OPS table")
            continue
        if op.classical_expr != expected_classical:
            errors.append(
                f"{key}: classical expr drifted: {op.classical_expr!r} != "
                f"{expected_classical!r}"
            )
        if op.quantum_expr != expected_quantum:
            errors.append(
                f"{key}: quantum expr drifted: {op.quantum_expr!r} != "
                f"{expected_quantum!r}"
            )
    return errors


# ---------------------------------------------------------------------------
# Plotting (matplotlib imported lazily -- workflow Stage 4, step 3).
# ---------------------------------------------------------------------------


def plot_query_model(out_dir: Path, constants: CostConstants) -> Path:
    """Chart family 1: clean query-model asymptotics, labeled as such.

    O(sqrt(N)) vs O(N) and O(1/eps) vs O(1/eps^2) -- 'query complexity under
    A1-A4 -- [Theoretical]' (workflow Stage 4, step 3). No wall-clock
    constants are applied here by design; that honesty split is the point.
    """
    import matplotlib

    matplotlib.use("Agg")  # headless-safe
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    n_vals = _log_grid(1e2, 1e16)
    ax1.loglog(n_vals, n_vals, label="Classical Theta(N) queries")
    ax1.loglog(n_vals, [math.sqrt(v) for v in n_vals], label="Quantum O(sqrt(N)) queries")
    ax1.set_xlabel("N (batch / search-space size)")
    ax1.set_ylabel("oracle queries")
    ax1.set_title("Per-component mean estimation\n(Grover/QAE vs classical sampling)")
    ax1.legend()
    ax1.grid(True, which="both", alpha=0.3)

    inv_eps = _log_grid(1e1, 1e10)
    ax2.loglog(inv_eps, [v**2 for v in inv_eps], label="Classical Theta(1/eps^2) samples")
    ax2.loglog(inv_eps, inv_eps, label="Quantum O(1/eps) QAE calls")
    ax2.set_xlabel("1/eps (inverse precision)")
    ax2.set_ylabel("sampler calls")
    ax2.set_title("Amplitude estimation vs Monte Carlo")
    ax2.legend()
    ax2.grid(True, which="both", alpha=0.3)

    fig.suptitle(
        "Query complexity under A1-A4 -- [Theoretical]\n"
        "(no oracle-synthesis, I/O, or clock-rate constants applied; see "
        "crossover_wall_clock.png for those)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    out_path = out_dir / "speedup_query_model.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_wall_clock(out_dir: Path, constants: CostConstants) -> Path:
    """Chart family 2: wall-clock-adjusted curves with the honest constants.

    Applies the clock deficit (10^8-10^10x), oracle-synthesis constants
    (10^2-10^4) and the d-factor; per research doc Section 6.5 the
    gradient-step crossover requires N >> 10^14-10^16 when d ~ 10^7-10^8.
    Axes extend far enough to make the *absence* of a realistic crossover
    visible rather than cropping to flatter a curve (workflow Stage 4,
    step 3).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(17, 5.5))

    # --- Panel 1: gradient step (the headline) -----------------------------
    n_vals = _log_grid(1e2, 1e20)
    classical = [
        classical_wall_clock(_grad_classical_full_batch(n, constants), constants)
        for n in n_vals
    ]
    sgd = [
        classical_wall_clock(_grad_classical_sgd(n, constants), constants)
        for n in n_vals
    ]
    q_best = [
        quantum_wall_clock(_grad_quantum_qge(n, constants), constants, best_case=True)
        for n in n_vals
    ]
    q_worst = [
        quantum_wall_clock(_grad_quantum_qge(n, constants), constants, best_case=False)
        for n in n_vals
    ]
    ax1.loglog(n_vals, classical, label="Classical full-batch O(N*C_f)")
    ax1.loglog(n_vals, sgd, linestyle=":", label="Classical SGD O(B*C_f) [honest baseline]")
    ax1.fill_between(
        n_vals,
        q_best,
        q_worst,
        alpha=0.25,
        label="Quantum QGE-ATTN O(d*sqrt(N)*C_f) (constant range)",
    )
    ax1.loglog(n_vals, q_best, linewidth=0.8)
    ax1.axvline(
        REALISTIC_N_CEILING,
        color="gray",
        linestyle="--",
        label="N = 10^14 (~d^2): edge of any realistic batch regime",
    )
    ax1.set_xlabel("batch size N")
    ax1.set_ylabel("seconds per gradient update")
    ax1.set_title(
        "Gradient step: NO crossover for N <= 10^14\n"
        "(crossover requires d << sqrt(N), Section 6.5(1))"
    )
    ax1.legend(fontsize=7)
    ax1.grid(True, which="both", alpha=0.3)

    # --- Panel 2: mean estimation (softmax/sampling) ------------------------
    inv_eps = _log_grid(1e1, 1e18)
    c_mean = [
        classical_wall_clock(_mean_classical(v, constants) * constants.c_f, constants)
        for v in inv_eps
    ]
    q_mean_best = [
        quantum_wall_clock(
            _mean_qae(v, constants) * constants.c_f, constants, best_case=True
        )
        for v in inv_eps
    ]
    q_mean_worst = [
        quantum_wall_clock(
            _mean_qae(v, constants) * constants.c_f, constants, best_case=False
        )
        for v in inv_eps
    ]
    ax2.loglog(inv_eps, c_mean, label="Classical MC Theta(1/eps^2)")
    ax2.fill_between(
        inv_eps, q_mean_best, q_mean_worst, alpha=0.25, label="QAE O(1/eps) (constant range)"
    )
    ax2.loglog(inv_eps, q_mean_best, linewidth=0.8)
    xover = constants.oracle_synthesis_low * constants.clock_deficit_low
    ax2.axvline(
        xover,
        color="gray",
        linestyle="--",
        label=f"best-case crossover 1/eps ~ {xover:.0e}\n(no training regime needs this precision)",
    )
    ax2.set_xlabel("1/eps (inverse precision)")
    ax2.set_ylabel("seconds per estimate")
    ax2.set_title(
        "Mean estimation (softmax/sampling):\ncrossover only at absurd precision"
    )
    ax2.legend(fontsize=7)
    ax2.grid(True, which="both", alpha=0.3)

    # --- Panel 3: matvec / linear solve --------------------------------------
    dims = _log_grid(1e1, 1e12)
    c_mv = [
        classical_wall_clock(_matvec_classical(n, constants), constants) for n in dims
    ]
    q_state = [
        quantum_wall_clock(
            _matvec_hhl_state_only(n, constants), constants, best_case=True
        )
        for n in dims
    ]
    q_read = [
        quantum_wall_clock(
            _matvec_hhl_classical_readout(n, constants), constants, best_case=True
        )
        for n in dims
    ]
    ax3.loglog(dims, c_mv, label="Classical dense matvec O(n^2) [op framing]")
    ax3.loglog(
        dims,
        q_state,
        linestyle="--",
        label="HHL state-output-only (excl. O(n^2) qRAM build) [best case]",
    )
    ax3.loglog(
        dims, q_read, linestyle="-.", label="HHL + Omega(n/eps^2) classical readout"
    )
    ax3.set_xlabel("matrix dimension n")
    ax3.set_ylabel("seconds per application")
    ax3.set_title(
        "Matvec/solve: state-only crossover exists but\n"
        "readout + qRAM build (caveats [4]) erase it"
    )
    ax3.legend(fontsize=7)
    ax3.grid(True, which="both", alpha=0.3)

    fig.suptitle(
        "Wall-clock-adjusted comparison -- oracle synthesis 10^2-10^4, clock "
        "deficit 10^8-10^10x, readout Omega(n/eps^2) applied\n"
        "Gradient-step caption: crossover requires d << sqrt(N) (Section "
        "6.5(1)); for d ~ 10^7-10^8 this means N >> 10^14-10^16 -- "
        "no realistic crossover exists. [Theoretical] accounting, [Proven] "
        "arithmetic.",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    out_path = out_dir / "crossover_wall_clock.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the command-line interface (workflow Stage 4 + assignment:
    --table-only, --out-dir, --verify)."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate the Stage 4 complexity comparison table and crossover "
            "plots for qml-accelerator (no matplotlib needed with "
            "--table-only)."
        )
    )
    parser.add_argument(
        "--table-only",
        action="store_true",
        help="print the text tables and crossover findings only; skip "
        "matplotlib figures entirely",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="output directory; complexity_table.md goes here and figures "
        "into <out-dir>/figures/ (default: this script's directory)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="assert the symbolic cost models match the research doc's "
        "stated complexities (exit nonzero on drift)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: render tables, optionally verify and plot.

    Returns a process exit code (0 on success, 1 on --verify drift).
    """
    args = build_arg_parser().parse_args(argv)
    constants = CostConstants()

    if args.verify:
        errors = verify_cost_models()
        if errors:
            for err in errors:
                print(f"VERIFY FAIL: {err}", file=sys.stderr)
            return 1
        print("VERIFY OK: cost models match docs/research/01-qml-accelerator.md "
              "Tables 1-3 (matvec row carries the documented framing difference).")

    table_md = render_complexity_table(constants)
    print(table_md)

    if args.table_only:
        print("(--table-only: figures skipped; no matplotlib imported)")
        return 0

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / "complexity_table.md"
    table_path.write_text(table_md, encoding="utf-8")
    print(f"wrote {table_path}")

    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    try:
        p1 = plot_query_model(figures_dir, constants)
        p2 = plot_wall_clock(figures_dir, constants)
        print(f"wrote {p1}")
        print(f"wrote {p2}")
    except ImportError:
        print(
            "matplotlib is not installed -- figures skipped. Re-run with "
            "--table-only to silence this, or `pip install -r "
            "qml-accelerator/requirements.txt`.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
