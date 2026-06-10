#!/usr/bin/env python3
"""HybridBoard thermal/power simulation (workflow Stage 5).

THEORETICAL REFERENCE MODEL — TRL 2-3. This script models the power and
thermal envelope of the hypothetical HybridBoard platform; it does not
measure, control, or communicate with any hardware.

Sources of truth
----------------
All anchor values are taken **exactly** from the research document,
``docs/research/03-hybrid-board.md`` §6 ("Power Architecture"), and the
process is defined by ``docs/workflows/03-hybridboard-workflow.md`` Stage 5.
The §6 power table for the superconducting (SC) variant, reused verbatim:

=====================================  ==========  ==========  ============
Subsystem                              50 qubits   500 qubits  5,000 qubits
=====================================  ==========  ==========  ============
Dilution refrigerator                  10-15 kW    20-30 kW    50-100 kW
  (pulse tubes, compressors, pumps)    [Demonstrated] anchors   [Speculative]
QPU control electronics                2-5 kW      15-40 kW    100-250 kW
  (room-temp RFSoC/sequencers,         [Demonstrated] per-channel anchors /
   ~2-4 ch/qubit)                      [Theoretical] scaling
Classical complex                      1.5-2.5 kW  2.5-5 kW    10-30 kW
  (CPU + 1x GPU + NPU + DRAM + NVMe)   [Demonstrated] component TDPs
Power conversion / distribution        ~1.5-2 kW   ~4-7 kW     ~15-40 kW
  losses (~10%)                        [Theoretical]
TOTAL "board" (really: installation)   ~15-25 kW   ~40-80 kW   ~175 kW-0.4 MW
                                       [Speculative] at 5,000 q
Cross-check vs ~6 W/qubit all-in       0.3 kW/q    ~0.1 kW/q   ~0.04-0.08 kW/q
  (RAND [Theoretical])
=====================================  ==========  ==========  ============

Additional §6 anchors reused here:

* Wall-to-cold efficiency of pulse-tube cryocoolers ~1:1500 **[Demonstrated]**
  — the dilution refrigerator runs at full load regardless of QPU
  utilization, which is why the cryoplant column below is *invariant across
  workload mixes* (workflow Stage 5, step 3 requires the model to
  demonstrate this).
* Room-temperature contrast: a neutral-atom QPU subsystem at ~3 kW
  **[Demonstrated]** plus a ~2 kW classical complex yields a ~5-6 kW total —
  "a high-end server rack budget, not a facility budget."

Model semantics
---------------
* Workload mixes (CPU_HEAVY / GPU_HEAVY / QPU_HEAVY / BALANCED) are
  classical-side weightings: they position the classical-complex and
  control-electronics draws inside their research-doc (min, max) ranges
  (e.g. QPU-heavy pushes decoder GPUs and sequencer channels toward
  range-max). They never touch the cryoplant draw.
* Interpolation between the 50/500/5,000-qubit anchors is log-space in
  qubit count (workflow Stage 5, step 2). Extrapolation beyond 5,000 qubits
  is **refused** unless ``speculative=True`` (``--speculative`` on the CLI),
  because the 5,000-qubit column is already tagged [Speculative] in the
  research doc (workflow Risk #7).
* Computation is numpy-only; matplotlib is imported lazily inside the plot
  functions so ``--table-only`` and ``--check`` run without it.

Usage
-----
    python3 power_model.py --table-only                  # markdown tables
    python3 power_model.py --mix qpu-heavy --qubits 1200 # one mix, one size
    python3 power_model.py --plot-dir out/               # also write PNG
    python3 power_model.py --check                       # self-verification
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

import numpy as np

# --------------------------------------------------------------------------
# Research-doc §6 anchor data (values copied exactly; tags carried verbatim)
# --------------------------------------------------------------------------

#: Qubit counts at which research doc §6 provides anchor columns.
ANCHOR_QUBITS: Final[tuple[int, int, int]] = (50, 500, 5_000)

#: Fractional conversion/distribution loss, research doc §6: "~10%"
#: [Theoretical].
CONVERSION_LOSS_FRACTION: Final[float] = 0.10

#: Room-temperature variant anchors, research doc §6 closing paragraph:
#: neutral-atom QPU ~3 kW [Demonstrated]; classical complex ~2 kW.
NEUTRAL_ATOM_QPU_KW: Final[float] = 3.0
ROOM_TEMP_CLASSICAL_KW: Final[float] = 2.0

#: §6 cross-check band at 5,000 qubits: "converging toward ~0.04-0.08
#: kW/qubit" [Theoretical].
KW_PER_QUBIT_BAND_5000: Final[tuple[float, float]] = (0.04, 0.08)

#: Pulse-tube wall-to-cold efficiency, §6: ~1:1500 [Demonstrated].
WALL_TO_COLD_RATIO: Final[int] = 1500


@dataclass(frozen=True)
class PowerRange:
    """A (min, max) power band in kW with its research-doc claim tag."""

    min_kw: float
    max_kw: float
    tag: str

    @property
    def mid_kw(self) -> float:
        """Midpoint of the band, used for mix-independent draws."""
        return 0.5 * (self.min_kw + self.max_kw)

    def at(self, fraction: float) -> float:
        """Linear position inside the band; ``fraction`` in [0, 1]."""
        if not 0.0 <= fraction <= 1.0:
            raise ValueError(f"fraction {fraction} outside [0, 1]")
        return self.min_kw + fraction * (self.max_kw - self.min_kw)


@dataclass(frozen=True)
class SCBoardAnchor:
    """One column of the research doc §6 SC power table (a qubit count)."""

    qubits: int
    cryoplant: PowerRange     # dilution refrigerator row
    control: PowerRange       # QPU control electronics row
    classical: PowerRange     # classical complex row
    total: PowerRange         # published TOTAL row (canonical bounds)


#: The §6 table, transcribed column-by-column. Totals are the doc's own
#: published bounds (15-25 / 40-80 / 175-400 kW) and serve as the canonical
#: acceptance ranges for ``--check``.
SC_ANCHORS: Final[tuple[SCBoardAnchor, SCBoardAnchor, SCBoardAnchor]] = (
    SCBoardAnchor(
        qubits=50,
        cryoplant=PowerRange(10.0, 15.0, "[Demonstrated] (1 small cryostat)"),
        control=PowerRange(2.0, 5.0, "[Demonstrated] per-channel anchors"),
        classical=PowerRange(1.5, 2.5, "[Demonstrated] component TDPs"),
        total=PowerRange(15.0, 25.0, "[Demonstrated]-anchored"),
    ),
    SCBoardAnchor(
        qubits=500,
        cryoplant=PowerRange(20.0, 30.0, "[Demonstrated] (1 large cryostat)"),
        control=PowerRange(15.0, 40.0, "[Theoretical] scaling"),
        classical=PowerRange(2.5, 5.0, "[Demonstrated] component TDPs"),
        total=PowerRange(40.0, 80.0, "[Demonstrated]-anchored"),
    ),
    SCBoardAnchor(
        qubits=5_000,
        cryoplant=PowerRange(50.0, 100.0, "[Speculative] (multi-cryostat)"),
        control=PowerRange(100.0, 250.0, "[Theoretical] scaling"),
        classical=PowerRange(10.0, 30.0, "[Demonstrated] component TDPs"),
        total=PowerRange(175.0, 400.0, "[Speculative]"),
    ),
)


@dataclass(frozen=True)
class WorkloadMix:
    """Classical-side workload weighting (workflow Stage 5, step 3).

    ``f_control`` / ``f_classical`` position the control-electronics and
    classical-complex draws within their research-doc (min, max) ranges.
    The cryoplant draw takes NO fraction: the dilution refrigerator runs at
    full load regardless of utilization (wall-to-cold ~1:1500
    [Demonstrated], research doc §6).
    """

    name: str
    f_control: float
    f_classical: float
    description: str


#: The four mixes required by workflow Stage 5. Fraction values are model
#: choices (the research doc fixes the ranges, not the utilization points);
#: QPU-heavy pushes decoder GPUs and sequencer channels toward range-max.
WORKLOAD_MIXES: Final[dict[str, WorkloadMix]] = {
    "cpu-heavy": WorkloadMix(
        "CPU_HEAVY", f_control=0.2, f_classical=0.6,
        description="host-side pre/post-processing dominates; QPU mostly idle",
    ),
    "gpu-heavy": WorkloadMix(
        "GPU_HEAVY", f_control=0.3, f_classical=0.9,
        description="decoder/simulation GPUs near TDP; light QPU duty",
    ),
    "qpu-heavy": WorkloadMix(
        "QPU_HEAVY", f_control=0.9, f_classical=0.8,
        description="sequencer channels + decoder GPUs toward range-max",
    ),
    "balanced": WorkloadMix(
        "BALANCED", f_control=0.5, f_classical=0.5,
        description="mid-range draw on all utilization-sensitive subsystems",
    ),
}


@dataclass(frozen=True)
class BoardPower:
    """Computed power breakdown for one (qubit count, workload mix) point."""

    qubits: int
    mix: str
    cryoplant_kw: float
    control_kw: float
    classical_kw: float

    @property
    def conversion_loss_kw(self) -> float:
        """~10% conversion/distribution losses [Theoretical], §6."""
        return CONVERSION_LOSS_FRACTION * (
            self.cryoplant_kw + self.control_kw + self.classical_kw
        )

    @property
    def total_kw(self) -> float:
        """Installation TDP including conversion losses."""
        return (
            self.cryoplant_kw + self.control_kw + self.classical_kw
            + self.conversion_loss_kw
        )

    @property
    def kw_per_qubit(self) -> float:
        """All-in kW per physical qubit (the §6 cross-check row)."""
        return self.total_kw / self.qubits


@dataclass(frozen=True)
class RoomTempBoard:
    """HybridBoard-RT configuration (neutral atom / trapped ion variant).

    Research doc §6: neutral-atom QPU ~3 kW [Demonstrated] + ~2 kW classical
    complex ≈ 5-6 kW total — a server-rack budget, not a facility budget.
    """

    qpu_kw: float = NEUTRAL_ATOM_QPU_KW
    classical_kw: float = ROOM_TEMP_CLASSICAL_KW

    @property
    def total_kw(self) -> float:
        """RT total including the same ~10% conversion-loss model."""
        subtotal = self.qpu_kw + self.classical_kw
        return subtotal * (1.0 + CONVERSION_LOSS_FRACTION)


# --------------------------------------------------------------------------
# Interpolation (log-space in qubit count, workflow Stage 5 step 2)
# --------------------------------------------------------------------------

def _interp_log(qubits: int, anchor_values: Sequence[float],
                speculative: bool) -> float:
    """Interpolate a subsystem value at ``qubits`` between §6 anchors.

    Interpolation is log-log (log power vs log qubit count). Requests below
    50 qubits are always refused (no anchor exists). Requests above 5,000
    qubits are refused unless ``speculative`` is True — the 5,000-qubit
    column is itself tagged [Speculative] (workflow Risk #7: "the model must
    refuse silent extrapolation beyond it").
    """
    if qubits < ANCHOR_QUBITS[0]:
        raise ValueError(
            f"{qubits} qubits is below the smallest research-doc anchor "
            f"({ANCHOR_QUBITS[0]}); no data supports this regime."
        )
    if qubits > ANCHOR_QUBITS[-1] and not speculative:
        raise ValueError(
            f"{qubits} qubits exceeds the 5,000-qubit anchor, which is "
            "already tagged [Speculative] in research doc §6. Pass "
            "speculative=True (--speculative) to extrapolate anyway."
        )
    log_q = np.log10(np.asarray(ANCHOR_QUBITS, dtype=float))
    log_v = np.log10(np.asarray(anchor_values, dtype=float))
    if qubits <= ANCHOR_QUBITS[-1]:
        return float(10.0 ** np.interp(np.log10(qubits), log_q, log_v))
    # Explicitly-requested speculative extrapolation: extend the slope of
    # the last anchor segment (500 -> 5,000) in log-log space.
    slope = (log_v[-1] - log_v[-2]) / (log_q[-1] - log_q[-2])
    return float(10.0 ** (log_v[-1] + slope * (np.log10(qubits) - log_q[-1])))


def sc_subsystem_band(qubits: int, subsystem: str,
                      speculative: bool = False) -> PowerRange:
    """Interpolated (min, max) band for one SC subsystem at ``qubits``.

    ``subsystem`` is one of ``cryoplant`` / ``control`` / ``classical`` /
    ``total``, matching the §6 table rows. The tag is taken from the nearest
    anchor at or above ``qubits`` (conservative: never promotes a tag).
    """
    ranges: list[PowerRange] = [
        getattr(anchor, subsystem) for anchor in SC_ANCHORS
    ]
    lo = _interp_log(qubits, [r.min_kw for r in ranges], speculative)
    hi = _interp_log(qubits, [r.max_kw for r in ranges], speculative)
    if qubits > ANCHOR_QUBITS[-1]:
        tag = "[Speculative] (extrapolated beyond research-doc anchors)"
    else:
        idx = next(i for i, a in enumerate(SC_ANCHORS) if qubits <= a.qubits)
        tag = ranges[idx].tag
    return PowerRange(lo, hi, tag)


# --------------------------------------------------------------------------
# Board TDP model
# --------------------------------------------------------------------------

def board_tdp(qubits: int, mix: WorkloadMix,
              speculative: bool = False) -> BoardPower:
    """Compute the SC-variant installation TDP at a qubit count and mix.

    The cryoplant draw is the band MAXIMUM and is independent of the mix:
    the dilution refrigerator runs at full load regardless of utilization
    (wall-to-cold efficiency ~1:1500 [Demonstrated], research doc §6) — this
    invariance is a required, demonstrable property of the model (workflow
    Stage 5, step 3). Control and classical draws are positioned inside
    their bands by the mix fractions.
    """
    cryo = sc_subsystem_band(qubits, "cryoplant", speculative)
    ctrl = sc_subsystem_band(qubits, "control", speculative)
    classical = sc_subsystem_band(qubits, "classical", speculative)
    return BoardPower(
        qubits=qubits,
        mix=mix.name,
        cryoplant_kw=cryo.max_kw,            # full load, mix-independent
        control_kw=ctrl.at(mix.f_control),
        classical_kw=classical.at(mix.f_classical),
    )


def dilution_fridge_curve(
    qubit_counts: Sequence[int], speculative: bool = False
) -> np.ndarray:
    """Dilution-refrigerator power band vs qubit count.

    Returns an array of shape (len(qubit_counts), 2) holding (min, max) kW
    per count, reusing the §6 anchors exactly: 10-15 kW at 50 q
    [Demonstrated], 20-30 kW at 500 q [Demonstrated], 50-100 kW at 5,000 q
    [Speculative].
    """
    rows = [
        (band.min_kw, band.max_kw)
        for band in (
            sc_subsystem_band(q, "cryoplant", speculative)
            for q in qubit_counts
        )
    ]
    return np.asarray(rows, dtype=float)


def cooling_comparison(
    speculative: bool = False,
) -> dict[str, tuple[float, float]]:
    """Contrast SC installation totals with the room-temperature variant.

    Returns variant -> (min_kw, max_kw): the SC totals at the three §6
    anchors (≈15-25 / 40-80 / 175-400 kW) against the room-temperature
    HybridBoard-RT total (~5-6 kW: neutral-atom QPU ~3 kW [Demonstrated]
    + ~2 kW classical), per research doc §6 and workflow Stage 5 step 4.
    """
    comparison: dict[str, tuple[float, float]] = {}
    for anchor in SC_ANCHORS:
        band = sc_subsystem_band(anchor.qubits, "total", speculative)
        comparison[f"SC @ {anchor.qubits} qubits"] = (band.min_kw, band.max_kw)
    # Research doc §6 states the RT band directly: "~5-6 kW total". We
    # report that band verbatim; the component model (3 + 2 kW + ~10%
    # losses = 5.5 kW) lands inside it, which run_check() verifies.
    comparison["RT (neutral atom), any scale shipped today"] = (5.0, 6.0)
    return comparison


# --------------------------------------------------------------------------
# Text output (numpy-only path; no matplotlib import)
# --------------------------------------------------------------------------

def format_power_table(qubit_counts: Sequence[int],
                       mix_keys: Sequence[str],
                       speculative: bool = False) -> str:
    """Render the per-mix TDP breakdown as a Markdown table.

    The cryoplant column repeats identically across mixes at each qubit
    count — that repetition is the point (mix-invariance, §6).
    """
    lines = [
        "| Qubits | Mix | Cryoplant kW (mix-invariant) | Control kW | "
        "Classical kW | Losses kW (~10%) | Total kW | kW/qubit | Tag |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in qubit_counts:
        total_band = sc_subsystem_band(q, "total", speculative)
        for key in mix_keys:
            bp = board_tdp(q, WORKLOAD_MIXES[key], speculative)
            lines.append(
                f"| {q:,} | {bp.mix} | {bp.cryoplant_kw:.1f} "
                f"| {bp.control_kw:.1f} | {bp.classical_kw:.1f} "
                f"| {bp.conversion_loss_kw:.1f} | {bp.total_kw:.1f} "
                f"| {bp.kw_per_qubit:.3f} | {total_band.tag} |"
            )
    return "\n".join(lines)


def format_cooling_table(speculative: bool = False) -> str:
    """Render the SC-vs-room-temperature cooling comparison as Markdown."""
    lines = [
        "| Variant | Total power (kW) | Anchor tag |",
        "|---|---|---|",
    ]
    tags = {
        "SC @ 50 qubits": "[Demonstrated] anchors (§6)",
        "SC @ 500 qubits": "[Demonstrated] anchors (§6)",
        "SC @ 5000 qubits": "[Speculative] (§6)",
        "RT (neutral atom), any scale shipped today":
            "[Demonstrated] (~3 kW QPU) — server-rack budget",
    }
    for variant, (lo, hi) in cooling_comparison(speculative).items():
        lines.append(
            f"| {variant} | {lo:.1f} – {hi:.1f} "
            f"| {tags.get(variant, '[Theoretical]')} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Plots (matplotlib imported lazily — may be absent at runtime)
# --------------------------------------------------------------------------

def plot_power_curves(plot_dir: Path, speculative: bool = False) -> Path:
    """Write the Stage 5 figure: TDP vs qubits per mix + cooling contrast.

    matplotlib is imported here, not at module level, so the numpy-only
    paths (``--table-only``, ``--check``) work without it. The 5,000-qubit
    SC points are annotated [Speculative] on the figure itself (workflow
    Stage 5, step 5).
    """
    import matplotlib  # noqa: PLC0415  (lazy by design)
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path = plot_dir / "power_model_output.png"

    qubit_axis = np.unique(
        np.geomspace(ANCHOR_QUBITS[0], ANCHOR_QUBITS[-1], 40).astype(int)
    )
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5))

    # Left: total TDP vs qubit count per mix (log-log).
    for key, mix in WORKLOAD_MIXES.items():
        totals = [
            board_tdp(int(q), mix, speculative).total_kw for q in qubit_axis
        ]
        ax1.loglog(qubit_axis, totals, label=mix.name)
    band = sc_subsystem_band(ANCHOR_QUBITS[-1], "total", speculative)
    ax1.annotate(
        "[Speculative]\n(research doc §6,\n5,000-qubit column)",
        xy=(ANCHOR_QUBITS[-1], band.min_kw),
        xytext=(1_200, 60),
        arrowprops={"arrowstyle": "->"},
        fontsize=9,
    )
    ax1.set_xlabel("Physical qubits (superconducting variant)")
    ax1.set_ylabel("Installation TDP (kW)")
    ax1.set_title("HybridBoard-SC total power vs qubit count\n"
                  "(model of research doc §6 — [Theoretical])")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend()

    # Right: SC vs room-temperature cooling load.
    comparison = cooling_comparison(speculative)
    labels = list(comparison)
    lows = np.array([comparison[k][0] for k in labels])
    highs = np.array([comparison[k][1] for k in labels])
    mids = 0.5 * (lows + highs)
    y = np.arange(len(labels))
    ax2.barh(y, mids, xerr=np.vstack([mids - lows, highs - mids]),
             capsize=4, color=["#b33", "#b33", "#b33", "#386"])
    ax2.set_yticks(y, labels, fontsize=8)
    ax2.set_xscale("log")
    ax2.set_xlabel("Total power (kW, log scale)")
    ax2.set_title("Cryogenic (SC) vs room-temperature (RT) cooling load\n"
                  "RT ≈ 5–6 kW [Demonstrated anchors]; SC @5,000 q "
                  "[Speculative]")
    ax2.grid(True, axis="x", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------
# Self-verification (workflow Stage 5, step 6)
# --------------------------------------------------------------------------

def run_check() -> int:
    """Assert model totals stay inside the research-doc §6 ranges.

    Checks (workflow Stage 5 acceptance criteria):
      1. For every mix, totals at 50/500/5,000 qubits fall inside
         ≈15-25 kW / ≈40-80 kW / ≈175-400 kW.
      2. The kW/qubit trend decreases monotonically and converges into the
         ~0.04-0.08 kW/qubit band at 5,000 qubits.
      3. Cryoplant draw is invariant across workload mixes.
      4. RT variant total lands in the ~5-6 kW band.
    Returns 0 on success, 1 on any violation.
    """
    failures: list[str] = []

    for anchor in SC_ANCHORS:
        cryo_values: set[float] = set()
        for key, mix in WORKLOAD_MIXES.items():
            bp = board_tdp(anchor.qubits, mix)
            cryo_values.add(round(bp.cryoplant_kw, 9))
            if not anchor.total.min_kw <= bp.total_kw <= anchor.total.max_kw:
                failures.append(
                    f"total {bp.total_kw:.1f} kW at {anchor.qubits} q "
                    f"({key}) outside §6 range "
                    f"[{anchor.total.min_kw}, {anchor.total.max_kw}]"
                )
        if len(cryo_values) != 1:
            failures.append(
                f"cryoplant draw varies across mixes at {anchor.qubits} q: "
                f"{sorted(cryo_values)} (must be mix-invariant, §6)"
            )

    lo, hi = KW_PER_QUBIT_BAND_5000
    for key, mix in WORKLOAD_MIXES.items():
        per_qubit = [
            board_tdp(a.qubits, mix).kw_per_qubit for a in SC_ANCHORS
        ]
        if not per_qubit[0] > per_qubit[1] > per_qubit[2]:
            failures.append(
                f"kW/qubit not monotonically converging for {key}: "
                f"{per_qubit}"
            )
        if not lo <= per_qubit[2] <= hi:
            failures.append(
                f"kW/qubit at 5,000 q for {key} = {per_qubit[2]:.4f}, "
                f"outside §6 band [{lo}, {hi}]"
            )

    rt = RoomTempBoard()
    if not 5.0 <= rt.total_kw <= 6.0:
        failures.append(
            f"RT total {rt.total_kw:.2f} kW outside §6 ~5-6 kW band"
        )

    if failures:
        print("power_model --check: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("power_model --check: OK — all totals inside research doc §6 "
          "ranges (15-25 / 40-80 / 175-400 kW), kW/qubit converges to "
          f"[{lo}, {hi}] at 5,000 q, cryoplant mix-invariant, RT ≈ "
          f"{rt.total_kw:.1f} kW.")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "HybridBoard thermal/power model (theoretical; reproduces "
            "research doc 03-hybrid-board.md §6)."
        ),
    )
    parser.add_argument(
        "--mix", choices=[*WORKLOAD_MIXES, "all"], default="all",
        help="workload mix to report (default: all four mixes)",
    )
    parser.add_argument(
        "--qubits", type=int, default=None,
        help="single qubit count to evaluate (default: the 50/500/5,000 "
             "research-doc anchors)",
    )
    parser.add_argument(
        "--table-only", action="store_true",
        help="print Markdown tables only; never import matplotlib",
    )
    parser.add_argument(
        "--plot-dir", type=Path, default=None,
        help="directory to write power_model_output.png (lazy matplotlib)",
    )
    parser.add_argument(
        "--speculative", action="store_true",
        help="permit extrapolation beyond the [Speculative] 5,000-qubit "
             "anchor (refused otherwise, per workflow Risk #7)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="self-verify against research doc §6 ranges; exit nonzero on "
             "violation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: tables to stdout, optional PNG, optional self-check."""
    args = build_parser().parse_args(argv)

    if args.check:
        return run_check()

    mix_keys = list(WORKLOAD_MIXES) if args.mix == "all" else [args.mix]
    qubit_counts = (
        [args.qubits] if args.qubits is not None else list(ANCHOR_QUBITS)
    )

    print("# HybridBoard power model — THEORETICAL (research doc §6)\n")
    print("Status: design concept — not a product specification. "
          "SC totals at 5,000 qubits are [Speculative].\n")
    print("## Installation TDP by workload mix (SC variant)\n")
    try:
        print(format_power_table(qubit_counts, mix_keys, args.speculative))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("\nNote: the cryoplant column is identical across mixes at each "
          "qubit count — the dilution refrigerator runs at full load "
          "regardless of utilization (wall-to-cold ~1:1500 [Demonstrated]).")
    print(f"Wall-to-cold ratio anchor: 1:{WALL_TO_COLD_RATIO} "
          "[Demonstrated] §6.\n")
    print("## Cryogenic vs room-temperature cooling comparison\n")
    print(format_cooling_table(args.speculative))

    if args.plot_dir is not None and not args.table_only:
        try:
            out = plot_power_curves(args.plot_dir, args.speculative)
        except ModuleNotFoundError as exc:
            # matplotlib may be absent at runtime; the tables above are the
            # dependency-free output path.
            print(f"\nplotting skipped: {exc} (install matplotlib>=3.8 per "
                  "hybrid-board/requirements.txt)", file=sys.stderr)
            return 3
        print(f"\nWrote figure: {out}")
    elif not args.table_only:
        print("\n(no --plot-dir given; pass one to render "
              "power_model_output.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
