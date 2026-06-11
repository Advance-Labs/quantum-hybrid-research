"""Stage 5 integration test: minimal "kernel init" through emulator + QLOS.

Workflow Stage 5 (docs/workflows/02-linux-workflow.md), realized against the
repo as built: the Stage 4 shim of the workflow text exists here as the QLOS
v0.1 runtime (quantum-linux/qos/qsyscalls.py ``QLOSRuntime``, the binding
design-doc contract -- quantum-linux/qos/QLOS-DESIGN-v0.1.md sections 4/8.3),
so this harness dispatches ALL quantum work through that four-call ABI.

The scripted init sequence, exactly as the research architecture prescribes
(docs/research/02-quantum-linux.md, "Proposed Architecture"): classical
steps -- init ordering, printk-style logging, a jiffies-style stage tick,
scheduler admission -- run as ordinary Python; quantum work flows ONLY
through ``qalloc``/``qexec``/``qmeasure``/``qfree``. Classical control flow
is deliberately NOT routed through the statevector: that would gain nothing
(quantum speedups are algorithm-specific [Proven] -- Grover/BBBV, Shor) and
would misrepresent the architecture (workflow Stage 5 step 1).

Init script (workflow Stage 5 step 1 + the Stage-5 builder assignment):

1. **Boot-time QPU probe** -- ISA load (QISA-v0.1.yaml), opcode census,
   qubit census over the lease manager's pool, and a MOCK per-qubit
   calibration table (the ``sysfs`` tree analogue; the emulator is
   noiseless, so the values are fabricated -- real tables drift hour to
   hour [Demonstrated], research doc, device-driver section).
2. **Lease-manager bring-up** -- ``qalloc`` smoke lease; check the
   ``qlease_desc`` mirror (LIVE state, CLOFORK|NODUP|NOMMAP flags,
   vq->pq table) and pool accounting across ``qfree``.
3. **Verifier self-test** -- (a) assemble-time: a use-after-measure program
   is rejected by ``qas`` with errno -ENOEXEC; (b) submit-time: a program
   touching qubits outside the real lease is rejected by ``qexec``
   (defense in depth, design doc section 6.3).
4. **First userland program** -- examples/hello_quantum.qs end-to-end
   through qas -> QLOS -> measured result (c0 == 1 every shot).
5. **Bell hello-world** -- examples/bell.qs (the uncorrected correlation
   variant from Stage 2, whose RESET preamble feeds the gate-count report);
   c0 == c1 in every shot, ~50/50 marginal within 5 sigma.
6. **Report** -- gate-execution counts and simulated runtime (workflow
   Stage 5 step 2): per-opcode ``gate_counts``, ``two_qubit_gate_count``,
   ``measure_count``, ``cycle_counter``, shots, wall-clock emulation time,
   peak statevector memory. ``--report`` dumps the JSON artifact to
   ``emulator/results/init-report.json`` (one reference copy is committed).

Honesty notes (what is emulated vs real):

* ``cycle_counter`` is the QWAIT cycle total of the executed shots. The
  per-job QCPUs live inside ``QPUScheduler.run_pending`` and are not
  surfaced, so the harness computes the total statically as
  sum(program.stats["qwait_cycles"] * shots) -- EXACT for the branch-free
  init programs, where every instruction executes once per shot (the same
  number ``QCPU.cycle_counter`` accumulates via ``QCPU.qwait``). It is NOT
  a timing or coherence model (workflow Risk 3); ``virtual_now_cycles`` is
  likewise admission-policy arithmetic [Theoretical], not physics.
* Peak statevector memory is the dense-emulator cost 16 * 2**n_qubits bytes
  for the largest lease -- an emulator-capacity figure, NOT the [Proven]
  Theta(4**n/eps**2) tomography bound (do not conflate; workflow
  Prerequisites note).
* The two-qubit budget assertion pins ONLY the demonstrated figure: 5,000
  reliable two-qubit gates on IBM's shipping Nighthawk [Demonstrated].

Run:
    /tmp/qhr-venv/bin/python -m pytest quantum-linux/emulator/
    /tmp/qhr-venv/bin/python quantum-linux/emulator/test_kernel_init.py --report
"""

from __future__ import annotations

import argparse
import errno as _errno
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Import seams (design doc section 8): emulator/, toolchain/, and qos/ are
# plain-module directories; sharing the seam keeps module identities single.
_EMULATOR_DIR = Path(__file__).resolve().parent
_QL_ROOT = _EMULATOR_DIR.parent
EXAMPLES_DIR: Path = _QL_ROOT / "examples"
RESULTS_DIR: Path = _EMULATOR_DIR / "results"
REPORT_PATH: Path = RESULTS_DIR / "init-report.json"

sys.path.insert(0, str(_EMULATOR_DIR))
sys.path.insert(0, str(_QL_ROOT / "toolchain"))
sys.path.insert(0, str(_QL_ROOT / "qos"))

import qcpu  # noqa: E402  (path seam must run first)
import qas  # noqa: E402
from qsyscalls import (  # noqa: E402
    MeasureResult,
    QLEASE_STATE_LIVE,
    QSET_F_CLOFORK,
    QSET_F_NODUP,
    QSET_F_NOMMAP,
    QLOSRuntime,
    VerifierRejectError,
)
from scheduler import estimate_cycles  # noqa: E402

SHOTS: int = 4096
SEED: int = 20260610
POOL_QUBITS: int = 8

#: 5-sigma window on a fair-coin ones-count over SHOTS trials
#: (workflow Stage 2 step 8 statistical tolerance, reused by Stage 5).
_FIVE_SIGMA: float = 5.0 * math.sqrt(SHOTS * 0.25)

#: Reliable two-qubit-gate budget of IBM's shipping Nighthawk processor
#: [Demonstrated] (workflow Stage 5 step 3; research doc, ISA realism note).
#: The ~7,500 end-of-2026 figure is roadmap [Speculative] and appears ONLY
#: in this comment -- never in an assertion (workflow Risk 7).
NIGHTHAWK_2Q_BUDGET: int = 5_000

#: Deliberately corrupted program: H after MEASURE without RESET. Rejected
#: at ASSEMBLE time by qas (load-time protection, design doc section 6.3).
USE_AFTER_MEASURE_ASM: str = """\
; verifier self-test: deliberate use-after-measure fault
        RESET   q0
        H       q0
        MEASURE q0 -> c0
        H       q0              ; fault: no RESET since MEASURE
"""

#: Program that assembles fine in isolation (own-size machine = 3 qubits)
#: but touches q2, outside the init harness's 2-qubit smoke lease: rejected
#: at SUBMIT time by qexec's lease-sized re-verification (defense in depth).
OUT_OF_LEASE_ASM: str = """\
; verifier self-test: valid program, but q2 is outside a 2-qubit lease
        RESET   q2
        X       q2
        MEASURE q2 -> c2
"""


def mock_calibration_table(n_qubits: int) -> dict[str, dict[str, float]]:
    """Build the boot-probe calibration table (the ``sysfs`` tree analogue).

    MOCK DATA: the statevector emulator is noiseless and has no T1/T2 or
    readout error, so these per-qubit figures are fabricated, deterministic
    placeholders shaped like what a real QPU driver would expose
    (research doc, device-driver section: "calibration as first-class
    state"; per-qubit fidelity drifts hour-to-hour [Demonstrated]). Nothing
    in the harness derives physics from them.

    Args:
        n_qubits: Number of physical qubits to fabricate entries for.

    Returns:
        Mapping ``"q<i>" -> {"t1_us", "t2_us", "readout_error"}``.
    """
    return {
        f"q{i}": {
            "t1_us": round(120.0 + 7.0 * math.sin(float(i)), 1),
            "t2_us": round(90.0 + 5.0 * math.cos(float(i)), 1),
            "readout_error": round(0.01 + 0.002 * (i % 3), 4),
        }
        for i in range(n_qubits)
    }


def _printk(log: list[str], t0: float, msg: str) -> None:
    """Append a printk-style line (monotonic seconds since init start)."""
    log.append(f"[{time.perf_counter() - t0:12.6f}] {msg}")


@dataclass
class InitResult:
    """Everything the init sequence produced.

    Attributes:
        report: JSON-serializable Stage 5 report (workflow step 2 keys).
        hello: Measurement shadow of the hello_quantum.qs run.
        bell: Measurement shadow of the bell.qs run.
        log: printk-style boot log lines.
    """

    report: dict[str, Any]
    hello: MeasureResult
    bell: MeasureResult
    log: list[str]


def kernel_init(*, shots: int = SHOTS, seed: int | None = SEED,
                n_pool_qubits: int = POOL_QUBITS) -> InitResult:
    """Run the scripted minimal kernel-init sequence (module docstring).

    Classical steps are ordinary Python; every quantum dispatch goes
    through the QLOS four-call ABI. Deterministic for a given ``seed``
    (per-job seeds derive at submit -- ``QPUScheduler`` contract).

    Args:
        shots: Shots per userland program (hello and bell each).
        seed: Master RNG seed for reproducible measurement sampling.
        n_pool_qubits: Physical pool size for the boot census.

    Returns:
        The :class:`InitResult` with the Stage 5 report.
    """
    log: list[str] = []
    t0 = time.perf_counter()
    jiffies = 0  # classical stage tick -- ordinary Python int

    _printk(log, t0, "qlos: kernel init sequence starting "
                     "(Stage 5 harness, emulated)")

    # -- stage 1: boot-time QPU probe ---------------------------------------
    jiffies += 1
    isa = qcpu.ISA()
    rt = QLOSRuntime(n_pool_qubits=n_pool_qubits, seed=seed, isa=isa)
    census = rt.lease_mgr.free_qubits()
    calibration = mock_calibration_table(n_pool_qubits)
    _printk(log, t0, f"qpu_core: probe: ISA {isa.meta.get('name')} "
                     f"v{isa.meta.get('version')} "
                     f"({len(isa.instructions)} opcodes, "
                     f"yaml={isa.loaded_from_yaml})")
    _printk(log, t0, f"qpu_core: probe: qubit census {census}/"
                     f"{n_pool_qubits} free; calibration table "
                     f"{len(calibration)} entries (MOCK -- emulator is "
                     "noiseless)")

    # -- stage 2: lease-manager bring-up (qalloc smoke lease) ---------------
    jiffies += 1
    smoke_fd = rt.qalloc(2, min_t2_us=200)
    info = rt.lease_info(smoke_fd)
    lease_mgr_report: dict[str, Any] = {
        "smoke_fd": smoke_fd,
        "lease_id": info.lease_id,
        "state_live": info.state == QLEASE_STATE_LIVE,
        "flags_ok": info.flags
        == (QSET_F_CLOFORK | QSET_F_NODUP | QSET_F_NOMMAP),
        "vq_to_pq": list(info.vq_to_pq),
        "free_during_lease": rt.lease_mgr.free_qubits(),
    }
    _printk(log, t0, f"qpu_core: lease bring-up: qset fd {smoke_fd} "
                     f"(lease {info.lease_id}, vq->pq {info.vq_to_pq}); "
                     f"pool {rt.lease_mgr.free_qubits()}/{n_pool_qubits} "
                     "free")

    # -- stage 3: verifier self-test (-ENOEXEC both layers) -----------------
    jiffies += 1
    assemble_reject = False
    try:
        qas.assemble(USE_AFTER_MEASURE_ASM)
    except qcpu.QISAVerifierError as exc:
        assemble_reject = exc.errno == -_errno.ENOEXEC
    qexec_reject = False
    try:
        rt.qexec(smoke_fd, qas.assemble(OUT_OF_LEASE_ASM), shots=1)
    except VerifierRejectError as exc:
        qexec_reject = exc.qlos_errno == -_errno.ENOEXEC
    _printk(log, t0, "qpu_core: verifier self-test: assemble-time reject="
                     f"{assemble_reject}, qexec-time reject={qexec_reject} "
                     "(-ENOEXEC, the quantum W^X analogue)")
    rt.qfree(smoke_fd)
    lease_mgr_report["free_after_qfree"] = rt.lease_mgr.free_qubits()
    _printk(log, t0, f"qpu_core: lease bring-up: qfree -> pool "
                     f"{rt.lease_mgr.free_qubits()}/{n_pool_qubits} free")

    # -- stage 4: first userland program (hello_quantum.qs via qas->QLOS) ---
    jiffies += 1
    hello_qobj = qas.assemble_file(EXAMPLES_DIR / "hello_quantum.qs")
    fd = rt.qalloc(max(hello_qobj.n_qubits, 1))
    rt.qexec(fd, hello_qobj, shots=shots)
    hello_res = rt.qmeasure(fd)
    rt.qfree(fd)
    _printk(log, t0, f"init: userland: hello_quantum.qs -> "
                     f"{hello_res.shots} shots, counts "
                     f"{hello_res.counts()} (est "
                     f"{estimate_cycles(hello_qobj)} cycles/shot)")

    # -- stage 5: Bell hello-world (uncorrected correlation variant) --------
    jiffies += 1
    bell_qobj = qas.assemble_file(EXAMPLES_DIR / "bell.qs")
    fd = rt.qalloc(bell_qobj.n_qubits, min_t2_us=200)
    rt.qexec(fd, bell_qobj, shots=shots, fidelity_floor=95)
    bell_res = rt.qmeasure(fd)
    rt.qfree(fd)
    _printk(log, t0, f"init: userland: bell.qs -> {bell_res.shots} shots, "
                     f"counts {bell_res.counts()} (est "
                     f"{estimate_cycles(bell_qobj)} cycles/shot)")

    # -- stage 6: report -----------------------------------------------------
    jiffies += 1
    stats = rt.stats()
    # QWAIT cycle total -- exact for these branch-free programs (module
    # docstring honesty note); NOT a timing model (workflow Risk 3).
    cycle_counter = (hello_qobj.stats["qwait_cycles"] * shots
                     + bell_qobj.stats["qwait_cycles"] * shots)
    max_lease_qubits = max(2, hello_qobj.n_qubits, bell_qobj.n_qubits)
    peak_statevector_bytes = 16 * 2 ** max_lease_qubits
    wall_clock_emulation_s = time.perf_counter() - t0
    _printk(log, t0, f"init: report: {stats['shot_count']} shots, "
                     f"2q gates {stats['two_qubit_gate_count']}, "
                     f"measures {stats['measure_count']}, QWAIT cycles "
                     f"{cycle_counter}, jiffies {jiffies}")

    report: dict[str, Any] = {
        "workflow_stage": "Stage 5: Emulator + Kernel Integration Test",
        "generated_by":
            "quantum-linux/emulator/test_kernel_init.py --report",
        "seed": seed,
        "shots_per_program": shots,
        "jiffies": jiffies,
        "isa": {
            "name": str(isa.meta.get("name")),
            "version": str(isa.meta.get("version")),
            "opcodes": len(isa.instructions),
            "loaded_from_yaml": isa.loaded_from_yaml,
        },
        "qpu_probe": {
            "n_pool_qubits": n_pool_qubits,
            "qubit_census_free": census,
            "calibration_table": calibration,
            "calibration_is_mock": True,
        },
        "lease_manager": lease_mgr_report,
        "verifier_selftest": {
            "assemble_time_reject": assemble_reject,
            "qexec_time_reject": qexec_reject,
        },
        # Workflow Stage 5 step 2 keys:
        "gate_counts": stats["gate_counts"],
        "two_qubit_gate_count": stats["two_qubit_gate_count"],
        "measure_count": stats["measure_count"],
        "cycle_counter": cycle_counter,
        "cycle_counter_note":
            "QWAIT cycle total of executed shots; computed statically as "
            "sum(stats.qwait_cycles * shots) -- exact for these branch-free "
            "programs; NOT a timing/coherence model (workflow Risk 3)",
        "shots": stats["shot_count"],
        "wall_clock_emulation_s": wall_clock_emulation_s,
        "peak_statevector_bytes": peak_statevector_bytes,
        "peak_statevector_note":
            "16 * 2**n_qubits for the largest lease -- emulator-capacity "
            "cost, NOT the [Proven] tomography bound",
        # Simulated runtime of the scheduler's virtual clock ([Theoretical]
        # admission-policy arithmetic, design doc section 5):
        "virtual_now_cycles": stats["virtual_now_cycles"],
        "two_qubit_gates_per_shot":
            stats["two_qubit_gate_count"] / max(stats["shot_count"], 1),
        "nighthawk_2q_budget_asserted": NIGHTHAWK_2Q_BUDGET,
        "scheduler": {
            "jobs_submitted": stats["jobs_submitted"],
            "jobs_completed": stats["jobs_completed"],
            "jobs_rejected": stats["jobs_rejected"],
            "jobs_cancelled": stats["jobs_cancelled"],
            "deadline_misses": stats["deadline_misses"],
        },
        "counts": {
            "hello_quantum": hello_res.counts(),
            "bell": bell_res.counts(),
        },
        "log": log,
    }
    return InitResult(report=report, hello=hello_res, bell=bell_res,
                      log=log)


# ---------------------------------------------------------------------------
# Pytest suite (workflow Stage 5 acceptance criteria)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def init() -> InitResult:
    """Run the init sequence once for the whole module (deterministic)."""
    return kernel_init()


def test_boot_probe_isa_and_qubit_census(init: InitResult) -> None:
    """Stage 1: ISA loads with the full QISA-K table; pool census is sane."""
    isa_block = init.report["isa"]
    assert isa_block["name"] == "QISA-K"
    assert isa_block["opcodes"] == 16  # 15 research-doc opcodes + BRN
    probe = init.report["qpu_probe"]
    assert probe["qubit_census_free"] == POOL_QUBITS
    assert probe["calibration_is_mock"] is True  # honesty: emulator is noiseless
    assert len(probe["calibration_table"]) == POOL_QUBITS
    for entry in probe["calibration_table"].values():
        assert set(entry) == {"t1_us", "t2_us", "readout_error"}


def test_boot_verifier_selftest_assemble_time() -> None:
    """Stage 3a: use-after-measure rejects at assemble time, -ENOEXEC."""
    with pytest.raises(qcpu.QISAVerifierError) as exc_info:
        qas.assemble(USE_AFTER_MEASURE_ASM)
    assert exc_info.value.errno == -_errno.ENOEXEC
    assert exc_info.value.rule == "no-use-after-measure-without-RESET"


def test_boot_verifier_selftest_qexec_time(init: InitResult) -> None:
    """Stage 3b: out-of-lease program rejects at qexec time, -ENOEXEC."""
    selftest = init.report["verifier_selftest"]
    assert selftest["assemble_time_reject"] is True
    assert selftest["qexec_time_reject"] is True
    # The rejected submission is accounted, never executed:
    assert init.report["scheduler"]["jobs_rejected"]["ENOEXEC"] == 1


def test_lease_manager_bringup(init: InitResult) -> None:
    """Stage 2: smoke lease is LIVE with enforced-invariant flags; pool
    accounting balances across qfree (no overcommit bookkeeping drift)."""
    lm = init.report["lease_manager"]
    assert lm["state_live"] is True
    assert lm["flags_ok"] is True  # CLOFORK|NODUP|NOMMAP always set
    assert len(lm["vq_to_pq"]) == 2
    assert lm["free_during_lease"] == POOL_QUBITS - 2
    assert lm["free_after_qfree"] == POOL_QUBITS


def test_first_userland_program_hello_quantum(init: InitResult) -> None:
    """Stage 4: hello_quantum.qs end-to-end -- c0 == 1 in every shot."""
    assert init.hello.shots == SHOTS
    assert init.hello.counts() == {"1": SHOTS}
    assert all(snap["c0"] == 1 for snap in init.hello.snapshots)


def test_bell_hello_world_correlated(init: InitResult) -> None:
    """Stage 5: uncorrected Bell -- c0 == c1 every shot, ~50/50 marginal."""
    assert init.bell.shots == SHOTS
    assert all(snap["c0"] == snap["c1"] for snap in init.bell.snapshots)
    assert set(init.bell.counts()) <= {"00", "11"}
    ones = sum(snap["c0"] for snap in init.bell.snapshots)
    assert abs(ones - SHOTS / 2) <= _FIVE_SIGMA


def test_teleport_example_feedforward_determinism() -> None:
    """examples/teleport.qs (research-doc feed-forward listing): c1 is the
    same constant (1) in every shot, c0 stays ~50/50; c0 == c1 is
    deliberately NOT asserted (workflow Stage 2 step 8 semantics)."""
    qobj = qas.assemble_file(EXAMPLES_DIR / "teleport.qs")
    rt = QLOSRuntime(n_pool_qubits=2, seed=SEED)
    fd = rt.qalloc(2, min_t2_us=200)
    rt.qexec(fd, qobj, shots=2048)
    res = rt.qmeasure(fd)
    rt.qfree(fd)
    assert all(snap["c1"] == 1 for snap in res.snapshots)
    ones = sum(snap["c0"] for snap in res.snapshots)
    assert abs(ones - 1024) <= 5.0 * math.sqrt(2048 * 0.25)


def test_gate_execution_counts_logged(init: InitResult) -> None:
    """Stage 5 acceptance: non-zero gate_counts for H, CNOT, MEASURE, RESET
    (plus the exact totals the two userland programs imply)."""
    gc = init.report["gate_counts"]
    for op in ("H", "CNOT", "MEASURE", "RESET"):
        assert gc.get(op, 0) > 0, f"gate_counts[{op!r}] must be non-zero"
    assert gc["H"] == SHOTS                # bell: 1 H/shot
    assert gc["CNOT"] == SHOTS             # bell: 1 CNOT/shot
    assert gc["X"] == SHOTS                # hello: 1 X/shot
    assert gc["RESET"] == 3 * SHOTS        # hello 1 + bell 2 per shot
    assert gc["MEASURE"] == 3 * SHOTS      # hello 1 + bell 2 per shot
    assert init.report["measure_count"] == 3 * SHOTS
    assert init.report["two_qubit_gate_count"] == SHOTS
    assert init.report["shots"] == 2 * SHOTS


def test_simulated_runtime_logged(init: InitResult) -> None:
    """Stage 5 acceptance: a cycle_counter total is reported (non-zero via
    hello_quantum's QWAIT), plus wall-clock time and peak memory."""
    assert init.report["cycle_counter"] == 8 * SHOTS  # QWAIT 8, hello only
    assert init.report["virtual_now_cycles"] > 0
    assert init.report["wall_clock_emulation_s"] > 0.0
    # 16 * 2**2 bytes: largest lease in the init sequence is 2 qubits --
    # emulator-capacity arithmetic, not the [Proven] tomography bound.
    assert init.report["peak_statevector_bytes"] == 64


def test_two_qubit_gate_budget_within_nighthawk(init: InitResult) -> None:
    """Workflow Stage 5 step 3: per-shot two-qubit gates <= 5,000 -- the
    reliable budget of IBM's shipping Nighthawk [Demonstrated]. (The ~7,500
    end-of-2026 roadmap figure is [Speculative]: comment-only, never
    asserted.)"""
    assert (init.report["two_qubit_gates_per_shot"]
            <= NIGHTHAWK_2Q_BUDGET)
    # Static per-program check over every shipped example as well:
    for example in ("hello_quantum.qs", "bell.qs", "teleport.qs"):
        qobj = qas.assemble_file(EXAMPLES_DIR / example)
        assert qobj.stats["two_qubit_gate_count"] <= NIGHTHAWK_2Q_BUDGET


def test_report_is_json_serializable_and_complete(init: InitResult) -> None:
    """The report carries every workflow Stage 5 step 2 key and round-trips
    through JSON (it must be dumpable to results/init-report.json)."""
    required = {
        "gate_counts", "two_qubit_gate_count", "measure_count",
        "cycle_counter", "shots", "wall_clock_emulation_s",
        "peak_statevector_bytes",
    }
    assert required <= set(init.report)
    round_tripped = json.loads(json.dumps(init.report))
    assert round_tripped["gate_counts"] == init.report["gate_counts"]


def test_reference_report_committed_and_complete() -> None:
    """Stage 5 acceptance: results/init-report.json exists and contains
    non-zero gate_counts for H, CNOT, MEASURE, RESET and a cycle_counter
    total. Regenerate with: python test_kernel_init.py --report"""
    assert REPORT_PATH.exists(), (
        f"{REPORT_PATH} missing -- regenerate with "
        f"'python {Path(__file__).name} --report'")
    data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    for op in ("H", "CNOT", "MEASURE", "RESET"):
        assert data["gate_counts"].get(op, 0) > 0
    assert data["cycle_counter"] > 0
    assert data["shots"] > 0


@pytest.mark.parametrize(
    "example", ["hello_quantum.qs", "bell.qs", "teleport.qs"])
def test_qrun_cli_runs_every_example(example: str) -> None:
    """The normalized dev loop closes: qrun.py runs each shipped example
    end-to-end (assemble -> qalloc -> qexec -> qmeasure -> qfree) and
    prints a counts histogram."""
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "qrun.py"),
         str(EXAMPLES_DIR / example), "--shots", "256", "--seed", "7"],
        capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "counts" in proc.stdout
    assert "qfree" in proc.stdout


def test_qrun_cli_trace_is_emulation_only_debugger() -> None:
    """qrun --trace single-steps a debug shot and carries the honesty
    banner (amplitude inspection is emulation-only [Proven])."""
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / "qrun.py"),
         str(EXAMPLES_DIR / "teleport.qs"),
         "--shots", "8", "--seed", "7", "--trace"],
        capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "EMULATION-ONLY" in proc.stdout
    assert "|00>" in proc.stdout  # amplitudes were printed


# ---------------------------------------------------------------------------
# CLI (--report mode, workflow Stage 5 step 2)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the init sequence from the shell; ``--report`` writes the JSON
    artifact to ``emulator/results/init-report.json``.

    Returns:
        0 on success (the init sequence itself raises on failure).
    """
    parser = argparse.ArgumentParser(
        prog="test_kernel_init.py",
        description="Stage 5 kernel-init harness: scripted init sequence "
                    "through qas -> QLOS -> qcpu; --report dumps the JSON "
                    "gate-count/runtime report.",
    )
    parser.add_argument("--report", action="store_true",
                        help="write results/init-report.json")
    parser.add_argument("--shots", type=int, default=SHOTS, metavar="N",
                        help=f"shots per userland program "
                             f"(default: {SHOTS})")
    parser.add_argument("--seed", type=int, default=SEED, metavar="S",
                        help=f"master RNG seed (default: {SEED})")
    args = parser.parse_args(argv)

    result = kernel_init(shots=args.shots, seed=args.seed)
    for line in result.log:
        print(line)
    if args.report:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps(result.report, indent=2) + "\n", encoding="utf-8")
        print(f"report written: {REPORT_PATH}")
    else:
        summary = {k: v for k, v in result.report.items() if k != "log"}
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
