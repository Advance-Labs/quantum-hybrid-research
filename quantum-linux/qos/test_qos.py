"""pytest suite for the QLOS v0.1 runtime (qos/qsyscalls.py, qos/scheduler.py).

Covers the workflow Stage 4-5 acceptance shape for the runtime layer
(docs/workflows/02-linux-workflow.md) against the BINDING contracts of
quantum-linux/qos/QLOS-DESIGN-v0.1.md sections 3-5 and 8:

* full syscall lifecycle (qalloc -> qexec -> qmeasure -> qfree);
* lease exclusivity + the no-duplication invariant (dup -> -EPERM;
  close-on-fork; consumed-lease reuse -> -EPERM) [Proven] no-cloning /
  measurement-postulate corollaries;
* coherence-budget admission control (-ETIME at submit, reservation);
* errno CONFORMANCE: the test parses kernel-patches/qsyscall.h's #defines
  with regexes and asserts the Python constants and exception errnos match
  the header exactly (via the stdlib errno module -- never hard-coded);
* multi-process multiplexing determinism under a seeded RNG.

Import mechanism (documented choice, design doc section 8): the runtime
modules are plain top-level modules behind ``sys.path`` seams -- each qos
module inserts ``../emulator`` (for ``qcpu``) and its own directory on
``sys.path``. This test does the same and imports ``qsyscalls`` /
``scheduler`` as plain modules, which keeps the suite collectable both as
``qos.test_qos`` (package import via qos/__init__.py, pytest prepend mode)
and stand-alone (``pytest quantum-linux/qos/test_qos.py``); either route
resolves to the same ``sys.modules`` entries. Test basenames across the
repo stay distinct so ``pytest quantum-linux/`` collects cleanly.

Run: /tmp/qhr-venv/bin/python -m pytest quantum-linux/qos/test_qos.py
"""

from __future__ import annotations

import errno
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0] / "emulator"))
sys.path.insert(0, str(_HERE))

import qcpu  # noqa: E402
import qsyscalls  # noqa: E402
import scheduler  # noqa: E402
from qsyscalls import (  # noqa: E402
    BadDescriptorError, CoherenceBudgetError, FidelityFloorError,
    LeaseStaleError, MeasureResult, PhysUndefinedError, PoolExhaustedError,
    QLEASE_STATE_CONSUMED, QLEASE_STATE_LIVE, QLEASE_STATE_STALE,
    QLOSRuntime, QMR_F_PARTIAL, QSET_F_CLOFORK, QSET_F_NODUP, QSET_F_NOMMAP,
    VerifierRejectError,
)
from scheduler import (  # noqa: E402
    COST_1Q, COST_2Q, COST_MEASURE, COST_RESET, CYCLES_PER_US,
    LeaseManager, QProcess, QProcState, QPUScheduler, estimate_cycles,
)

QSYSCALL_H = _HERE.parents[0] / "kernel-patches" / "qsyscall.h"

#: Static per-shot costs of the two canonical programs (design doc
#: section 5 cost table; straight-line/conservative w.r.t. branches).
BELL_UNCORRECTED_EST = 2 * COST_RESET + COST_1Q + COST_2Q + 2 * COST_MEASURE
BELL_FEEDFORWARD_EST = (2 * COST_RESET + 12          # QWAIT 12 immediate
                        + COST_1Q + COST_2Q          # H, CNOT
                        + 2 * COST_MEASURE
                        + COST_1Q)                   # branched-over X charged


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _shared_isa() -> qcpu.ISA:
    """One YAML-loaded ISA per session (avoids re-parsing per test)."""
    global _ISA_CACHE
    try:
        return _ISA_CACHE
    except NameError:
        _ISA_CACHE = qcpu.ISA()
        return _ISA_CACHE


def make_runtime(**kw) -> QLOSRuntime:
    """Seeded runtime with the shared ISA; kwargs override defaults."""
    kw.setdefault("n_pool_qubits", 8)
    kw.setdefault("seed", 42)
    kw.setdefault("isa", _shared_isa())
    return QLOSRuntime(**kw)


def parse_header_defines(text: str) -> dict[str, object]:
    """Extract ``#define NAME value`` pairs from qsyscall.h.

    Handles the header's three value spellings: plain ints (``463``,
    ``128u``), shift expressions (``(1u << 0)``), and negative-errno
    aliases (``(-EBUSY)`` -> the string ``"EBUSY"``).
    """
    out: dict[str, object] = {}
    for m in re.finditer(
            r"^#define\s+(\w+)\s+(.+?)\s*(?:/\*.*)?$", text, re.MULTILINE):
        name, raw = m.group(1), m.group(2).strip()
        if (mm := re.fullmatch(r"\(?\s*(\d+)u?\s*\)?", raw)):
            out[name] = int(mm.group(1))
        elif (mm := re.fullmatch(r"\(\s*(\d+)u?\s*<<\s*(\d+)\s*\)", raw)):
            out[name] = int(mm.group(1)) << int(mm.group(2))
        elif (mm := re.fullmatch(r"\(\s*-\s*(E\w+)\s*\)", raw)):
            out[name] = mm.group(1)
    return out


# ---------------------------------------------------------------------------
# 1. full syscall lifecycle: qalloc -> qexec -> qmeasure -> qfree
# ---------------------------------------------------------------------------


def test_full_lifecycle_bell_counts():
    """The design doc section 7 worked example, end to end."""
    rt = make_runtime()
    fd = rt.qalloc(2, min_t2_us=200)
    assert fd >= 3  # 0..2 stay conventionally classical
    job = rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=512,
                   fidelity_floor=95)
    assert job >= 0
    res = rt.qmeasure(fd)
    assert isinstance(res, MeasureResult)
    assert res.shots == 512 and res.n_qubits == 2
    assert res.flags == 0 and res.fidelity_est == 100
    counts = res.counts()
    assert set(counts) <= {"00", "11"}          # never '01'/'10'
    assert sum(counts.values()) == 512
    assert rt.qfree(fd) == 0
    assert rt.lease_mgr.free_qubits() == 8       # pool fully restored
    with pytest.raises(BadDescriptorError):      # capability is closed
        rt.lease_info(fd)


def test_lifecycle_lease_states_and_lease_info():
    rt = make_runtime()
    fd = rt.qalloc(3)
    info = rt.lease_info(fd)
    assert info.state == QLEASE_STATE_LIVE
    assert info.n_qubits == 3 and info.vq_to_pq == (0, 1, 2)
    assert info.cal_epoch == 1
    assert info.flags == QSET_F_CLOFORK | QSET_F_NODUP | QSET_F_NOMMAP
    rt.qexec(fd, qcpu.HELLO_QUANTUM_ASM, shots=4)
    rt.qmeasure(fd)
    assert rt.lease_info(fd).state == QLEASE_STATE_CONSUMED
    assert rt.qfree(fd) == 0                     # CONSUMED frees cleanly


def test_qexec_accepts_qobj_object_and_str():
    """qexec takes assembled objects or text (parity with QCPU.run)."""
    rt = make_runtime()
    qobj = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM, rt.isa)
    fd = rt.qalloc(2)
    rt.qexec(fd, qobj, shots=16)
    assert rt.qmeasure(fd).shots == 16


def test_measure_result_packed_shadow_layout():
    """Bit k = shot*n_qubits + qubit, LSB-first; len = (n*shots+7)//8."""
    rt = make_runtime()
    fd = rt.qalloc(1)
    rt.qexec(fd, qcpu.HELLO_QUANTUM_ASM, shots=10)  # c0 == 1 every shot
    res = rt.qmeasure(fd)
    packed = res.packed_shadow()
    assert len(packed) == (1 * 10 + 7) // 8 == 2
    assert packed == bytes([0xFF, 0x03])            # 10 set bits, LSB-first
    rt.qfree(fd)


def test_qmeasure_blocks_until_all_lease_jobs_complete():
    """v0.1 'blocking' = synchronously driving run_pending (section 4)."""
    rt = make_runtime()
    fd = rt.qalloc(2)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=8)
    rt.qexec(fd, qcpu.HELLO_QUANTUM_ASM, shots=8)
    assert rt.qpu_sched.pending_jobs() == 2          # nothing ran yet
    res = rt.qmeasure(fd)
    assert res.shots == 16                           # both jobs drained
    assert rt.qpu_sched.pending_jobs() == 0


# ---------------------------------------------------------------------------
# 2. lease exclusivity + no-duplication invariant
# ---------------------------------------------------------------------------


def test_dup_always_eperm():
    """dup() duplicates the resource = copying [Proven] -> -EPERM."""
    rt = make_runtime()
    fd = rt.qalloc(2)
    with pytest.raises(PhysUndefinedError) as ei:
        rt.dup(fd)
    assert ei.value.qlos_errno == -errno.EPERM
    assert rt.lease_info(fd).state == QLEASE_STATE_LIVE  # lease unharmed


def test_dup_unknown_fd_is_ebadf():
    with pytest.raises(BadDescriptorError):
        make_runtime().dup(99)


def test_no_overcommit_ever():
    """-EBUSY on exhaustion; qalloc never blocks (no swap exists)."""
    rt = make_runtime(n_pool_qubits=4)
    rt.qalloc(3)
    with pytest.raises(PoolExhaustedError) as ei:
        rt.qalloc(2)
    assert ei.value.qlos_errno == -errno.EBUSY
    rt.qalloc(1)                                     # exact fit still fine
    assert rt.lease_mgr.free_qubits() == 0


def test_physical_qubits_never_shared_between_live_leases():
    """One physical qubit belongs to at most one live lease (rule 2)."""
    rt = make_runtime(n_pool_qubits=6)
    fds = [rt.qalloc(2) for _ in range(3)]
    seen: set[int] = set()
    for fd in fds:
        pq = set(rt.lease_info(fd).vq_to_pq)
        assert not (pq & seen)
        seen |= pq
    assert seen == set(range(6))


def test_fork_is_close_on_fork_for_leases():
    """fork(): classical copy; the child holds NO leases (QSET_F_CLOFORK)."""
    mgr = LeaseManager(8)
    parent = QProcess(10, "parent")
    lease = mgr.allocate(parent, 2)
    child = parent.fork(11)
    assert child.pid == 11 and child.state is QProcState.NEW
    assert child.leases == {}                        # never duplicated
    assert parent.leases == {lease.lease_id: lease}  # parent keeps them
    assert child.name == parent.name                 # classical copy is fine
    child.stats["jobs_submitted"] = 99               # copies are independent
    assert parent.stats["jobs_submitted"] == 0


def test_exec_and_exit_revoke_leases():
    mgr = LeaseManager(8)
    proc = QProcess(20, "old-image")
    mgr.allocate(proc, 3)
    proc.exec_image("new-image")
    assert proc.leases == {} and proc.name == "new-image"
    assert mgr.free_qubits() == 8                    # RESET + returned
    mgr.allocate(proc, 2)
    proc.exit()
    assert proc.state is QProcState.ZOMBIE
    assert proc.leases == {} and mgr.free_qubits() == 8
    assert "jobs_submitted" in proc.stats            # stats retained


def test_consumed_lease_reuse_is_eperm():
    """qexec-after-qmeasure / second qmeasure: same violation class."""
    rt = make_runtime()
    fd = rt.qalloc(2)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    rt.qmeasure(fd)
    with pytest.raises(PhysUndefinedError):          # qexec after qmeasure
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    with pytest.raises(PhysUndefinedError):          # second qmeasure
        rt.qmeasure(fd)
    assert rt.stats()["jobs_rejected"]["EPERM"] == 1
    assert rt.qfree(fd) == 0                         # qfree always valid


def test_unknown_fd_is_ebadf_on_every_call():
    rt = make_runtime()
    for call in (lambda: rt.qexec(7, qcpu.HELLO_QUANTUM_ASM),
                 lambda: rt.qmeasure(7), lambda: rt.qfree(7),
                 lambda: rt.lease_info(7), lambda: rt.dup(7)):
        with pytest.raises(BadDescriptorError) as ei:
            call()
        assert ei.value.qlos_errno == -errno.EBADF
    fd = rt.qalloc(1)
    rt.qfree(fd)
    with pytest.raises(BadDescriptorError):          # double-qfree
        rt.qfree(fd)


# ---------------------------------------------------------------------------
# 3. admission control (-ETIME) + verifier (-ENOEXEC) + -ESTALE + -EIO
# ---------------------------------------------------------------------------


def test_admission_rejects_over_budget_circuit():
    """Estimate above the lease's coherence budget -> -ETIME at submit."""
    rt = make_runtime()
    budget_us = (BELL_UNCORRECTED_EST - 1) // CYCLES_PER_US  # too small
    fd = rt.qalloc(2, min_t2_us=max(budget_us, 1))
    with pytest.raises(CoherenceBudgetError) as ei:
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    assert ei.value.qlos_errno == -errno.ETIME
    assert rt.stats()["jobs_rejected"]["ETIME"] == 1
    assert rt.stats()["jobs_submitted"] == 0         # rejected at submit


def test_admission_reserves_budget_at_submit():
    """Conservative EDF admission: each admit deducts its estimate."""
    rt = make_runtime()
    # Budget fits exactly two Bell submissions, not three.
    budget_cycles = 2 * BELL_UNCORRECTED_EST + BELL_UNCORRECTED_EST // 2
    fd = rt.qalloc(2, min_t2_us=budget_cycles // CYCLES_PER_US)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    with pytest.raises(CoherenceBudgetError):
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    lease = rt.lease_mgr._leases[rt.lease_info(fd).lease_id]
    assert (lease.coherence_budget_cycles - lease.coherence_remaining_cycles
            == 2 * BELL_UNCORRECTED_EST)


def test_admission_rejects_job_exceeding_its_own_deadline():
    rt = make_runtime()
    fd = rt.qalloc(2, min_t2_us=10_000)              # huge lease budget
    too_tight_us = (BELL_UNCORRECTED_EST - 1) // CYCLES_PER_US
    with pytest.raises(CoherenceBudgetError):
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4,
                 deadline_us=max(too_tight_us, 1))


def test_estimate_cycles_cost_table():
    """Static per-shot estimate follows the section 5 cost table exactly,
    charging branched-over instructions (conservative straight-line sum)."""
    isa = _shared_isa()
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM, isa)
    ff = qsyscalls._assemble_source(qcpu.BELL_FEEDFORWARD_ASM, isa)
    assert estimate_cycles(bell) == BELL_UNCORRECTED_EST == 48
    assert estimate_cycles(ff) == BELL_FEEDFORWARD_EST == 61
    assert (COST_1Q, COST_2Q, COST_MEASURE, COST_RESET) == (1, 3, 10, 12)


def test_verifier_rejects_before_any_execution():
    """-ENOEXEC: unleased qubit / use-after-measure / malformed text."""
    rt = make_runtime()
    fd = rt.qalloc(2)
    cases = [
        "H q2\n",                                    # outside the lease
        "MEASURE q0 -> c0\nH q0\n",                  # use-after-measure
        "CNOT q0, q0\n",                             # operand duplication
        "FROBNICATE q0\n",                           # malformed text
    ]
    for bad in cases:
        with pytest.raises(VerifierRejectError) as ei:
            rt.qexec(fd, bad)
        assert ei.value.qlos_errno == -errno.ENOEXEC
    assert rt.stats()["jobs_rejected"]["ENOEXEC"] == len(cases)
    assert rt.stats()["jobs_completed"] == 0
    assert rt.stats()["shot_count"] == 0             # nothing executed


def test_recalibration_stales_live_leases():
    """-ESTALE seam: qexec/qmeasure fail, only qfree remains valid."""
    rt = make_runtime()
    fd = rt.qalloc(2)
    old_epoch = rt.lease_info(fd).cal_epoch
    new_epoch = rt.recalibrate()
    assert new_epoch == old_epoch + 1
    info = rt.lease_info(fd)
    assert info.state == QLEASE_STATE_STALE
    assert info.cal_epoch == old_epoch               # placement-time epoch
    with pytest.raises(LeaseStaleError) as ei:
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM)
    assert ei.value.qlos_errno == -errno.ESTALE
    with pytest.raises(LeaseStaleError):
        rt.qmeasure(fd)
    assert rt.qfree(fd) == 0                         # re-qalloc path open
    assert rt.lease_info(rt.qalloc(2)).cal_epoch == new_epoch


def test_fidelity_floor_eio_consumes_lease_without_data():
    """-EIO: the call fails INSTEAD OF returning data; lease consumed."""
    rt = make_runtime(readout_fidelity=80)           # emulated drift knob
    fd = rt.qalloc(2)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=8, fidelity_floor=95)
    with pytest.raises(FidelityFloorError) as ei:
        rt.qmeasure(fd)
    assert ei.value.qlos_errno == -errno.EIO
    info = rt.lease_info(fd)
    assert info.state == QLEASE_STATE_CONSUMED       # readout happened
    with pytest.raises(PhysUndefinedError):          # ...and was consumed
        rt.qmeasure(fd)


def test_ring_overflow_sets_partial_flag():
    """Bounded ring drops oldest shots -> QMR_F_PARTIAL, fewer shots."""
    rt = make_runtime(ring_capacity_shots=8)
    fd = rt.qalloc(1)
    rt.qexec(fd, qcpu.HELLO_QUANTUM_ASM, shots=20)
    res = rt.qmeasure(fd)
    assert res.shots == 8                            # capacity survived
    assert res.flags & QMR_F_PARTIAL


def test_qfree_cancels_still_queued_jobs():
    rt = make_runtime()
    fd = rt.qalloc(2)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4)
    assert rt.qpu_sched.pending_jobs() == 2
    rt.qfree(fd)
    s = rt.stats()
    assert rt.qpu_sched.pending_jobs() == 0
    assert s["jobs_cancelled"] == 2 and s["jobs_completed"] == 0


# ---------------------------------------------------------------------------
# 4. errno conformance against kernel-patches/qsyscall.h (parsed, not typed)
# ---------------------------------------------------------------------------

_HDR = parse_header_defines(QSYSCALL_H.read_text(encoding="utf-8"))

#: qsyscall.h QERR_* alias -> the Python exception class mirroring it.
QERR_TO_EXC = {
    "QERR_POOL_EXHAUSTED": PoolExhaustedError,
    "QERR_COHERENCE_BUDGET": CoherenceBudgetError,
    "QERR_VERIFIER_REJECT": VerifierRejectError,
    "QERR_FIDELITY_FLOOR": FidelityFloorError,
    "QERR_LEASE_STALE": LeaseStaleError,
    "QERR_PHYS_UNDEFINED": PhysUndefinedError,
}

_INT_CONSTANTS = [
    "QTOPO_ANY", "QTOPO_LINE", "QTOPO_GRID", "QTOPO_ALL2ALL",
    "QDEADLINE_RELAXED", "QMR_F_PARTIAL",
    "QLEASE_STATE_LIVE", "QLEASE_STATE_CONSUMED", "QLEASE_STATE_STALE",
    "QLEASE_MAX_QUBITS",
    "QSET_F_CLOFORK", "QSET_F_NODUP", "QSET_F_NOMMAP",
    "__NR_qalloc", "__NR_qexec", "__NR_qmeasure", "__NR_qfree",
]


@pytest.mark.parametrize("name", _INT_CONSTANTS)
def test_constant_matches_header(name: str):
    """Every mirrored constant equals the header's #define, by parsing."""
    assert name in _HDR, f"{name} missing from qsyscall.h"
    # getattr: dunder access is mangle-proof and works for __NR_* names.
    assert getattr(qsyscalls, name) == _HDR[name]


@pytest.mark.parametrize("qerr,exc", sorted(QERR_TO_EXC.items()))
def test_exception_errno_matches_header(qerr: str, exc: type):
    """QERR_* -> -E* aliases resolve through the stdlib errno module."""
    sym = _HDR[qerr]                                 # e.g. "EBUSY"
    assert isinstance(sym, str) and sym.startswith("E")
    expected = -getattr(errno, sym)
    assert exc.qlos_errno == expected
    inst = exc("conformance probe")
    assert inst.qlos_errno == expected               # instance view
    assert inst.errno == -expected                   # OSError convention
    assert isinstance(inst, qsyscalls.QLOSError)
    assert isinstance(inst, OSError)


def test_ebadf_is_deliberately_outside_the_quantum_table():
    """-EBADF is ordinary POSIX; the header's QERR table must not name it."""
    assert "EBADF" not in {v for v in _HDR.values() if isinstance(v, str)}
    assert BadDescriptorError.qlos_errno == -errno.EBADF


def test_qerr_table_is_covered_exactly():
    """Every QERR_* alias in the header has exactly one Python mirror."""
    header_qerrs = {k for k in _HDR if k.startswith("QERR_")}
    assert header_qerrs == set(QERR_TO_EXC)


# ---------------------------------------------------------------------------
# 5. scheduling: dispatch order, deadline misses, multi-process determinism
# ---------------------------------------------------------------------------


def _two_proc_setup(seed: int):
    """Two processes time-sharing one QPU (design doc section 5)."""
    mgr = LeaseManager(8)
    sched = QPUScheduler(mgr, seed=seed, isa=_shared_isa())
    alice, bob = QProcess(100, "alice"), QProcess(101, "bob")
    la = mgr.allocate(alice, 2, min_t2_us=1_000)
    lb = mgr.allocate(bob, 2, min_t2_us=1_000)
    return mgr, sched, alice, bob, la, lb


def test_deadline_jobs_dispatch_before_relaxed_fifo():
    """Finite-deadline jobs first (ascending), then relaxed FIFO."""
    _, sched, _, _, la, lb = _two_proc_setup(seed=7)
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM,
                                      _shared_isa())
    sched.submit(la, bell, shots=2)                  # relaxed, submitted 1st
    sched.submit(lb, bell, shots=2, deadline_us=500)  # deadline, 2nd
    assert sched.run_pending(max_jobs=1) == 1
    assert len(lb.ring) == 2 and len(la.ring) == 0   # deadline job won
    sched.run_pending()
    assert len(la.ring) == 2


def test_soft_deadline_miss_is_counted_job_still_runs():
    """Deadlines are soft in v0.1: a miss increments stats, never kills."""
    _, sched, alice, bob, la, lb = _two_proc_setup(seed=7)
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM,
                                      _shared_isa())
    tight_us = BELL_UNCORRECTED_EST // CYCLES_PER_US + 1  # fits one job only
    sched.submit(la, bell, shots=2, deadline_us=tight_us)
    sched.submit(lb, bell, shots=2, deadline_us=tight_us)
    assert sched.run_pending() == 2                  # both still ran
    s = sched.stats()
    assert s["deadline_misses"] == 1                 # second went past
    assert s["jobs_completed"] == 2
    assert len(la.ring) == 2 and len(lb.ring) == 2
    assert s["virtual_now_cycles"] == 2 * BELL_UNCORRECTED_EST


def test_process_lifecycle_states_through_scheduling():
    """NEW -> READY -> BLOCKED_ON_QPU -> READY -> ZOMBIE (section 3)."""
    mgr = LeaseManager(8)
    sched = QPUScheduler(mgr, seed=3, isa=_shared_isa())
    proc = QProcess(50, "demo")
    assert proc.state is QProcState.NEW
    lease = mgr.allocate(proc, 2)
    assert proc.state is QProcState.READY
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM,
                                      _shared_isa())
    sched.submit(lease, bell, shots=2)
    assert proc.state is QProcState.BLOCKED_ON_QPU
    sched.run_pending()
    assert proc.state is QProcState.READY            # jobs no longer queued
    proc.exit()
    assert proc.state is QProcState.ZOMBIE
    assert mgr.free_qubits() == 8                    # leases revoked


def test_per_process_and_global_stats():
    """Assignment contract: gate counts, shots, rejects -- both scopes."""
    _, sched, alice, bob, la, lb = _two_proc_setup(seed=11)
    isa = _shared_isa()
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM, isa)
    hello = qsyscalls._assemble_source(qcpu.HELLO_QUANTUM_ASM, isa)
    sched.submit(la, bell, shots=10)
    sched.submit(lb, hello, shots=5)
    with pytest.raises(VerifierRejectError):
        sched.submit(lb, qsyscalls._assemble_source("H q5\n", isa))
    sched.run_pending()
    assert alice.stats["shot_count"] == 10
    assert alice.stats["gate_counts"]["CNOT"] == 10
    assert alice.stats["jobs_rejected"]["ENOEXEC"] == 0
    assert bob.stats["shot_count"] == 5
    assert bob.stats["jobs_rejected"]["ENOEXEC"] == 1
    g = sched.stats()
    assert g["shot_count"] == 15 and g["jobs_completed"] == 2
    assert g["jobs_rejected"]["ENOEXEC"] == 1
    assert g["gate_counts"]["CNOT"] == 10            # bob's hello has none
    binding_keys = {"jobs_submitted", "jobs_completed", "jobs_rejected",
                    "jobs_cancelled", "deadline_misses",
                    "virtual_now_cycles", "gate_counts",
                    "two_qubit_gate_count", "measure_count", "shot_count"}
    assert binding_keys <= set(g)


def _multiplexed_outcome(seed: int) -> tuple:
    """Run an interleaved two-process workload; return all observables."""
    _, sched, alice, bob, la, lb = _two_proc_setup(seed)
    isa = _shared_isa()
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM, isa)
    ff = qsyscalls._assemble_source(qcpu.BELL_FEEDFORWARD_ASM, isa)
    sched.submit(la, bell, shots=16, deadline_us=400)
    sched.submit(lb, ff, shots=16)
    sched.submit(la, ff, shots=8)
    sched.submit(lb, bell, shots=8, deadline_us=300)
    sched.run_pending()
    return (tuple(tuple(sorted(s.items())) for s in la.ring),
            tuple(tuple(sorted(s.items())) for s in lb.ring),
            sched.stats())


def test_multi_process_multiplexing_is_deterministic_under_seed():
    """Same seed + same submission sequence => bit-identical shadows.

    Per-job seeds derive from the master seed AT SUBMIT (scheduler
    contract), so the interleaved workload replays exactly -- the
    classical-control-plane property that makes regression testing of a
    quantum runtime possible at all (only classical shadows are compared;
    the quantum states themselves admit no comparison [Proven]).
    """
    a = _multiplexed_outcome(seed=1234)
    b = _multiplexed_outcome(seed=1234)
    assert a == b
    c = _multiplexed_outcome(seed=4321)
    assert c[2]["shot_count"] == a[2]["shot_count"]  # same workload shape
    assert (a[0], a[1]) != (c[0], c[1])              # but different draws


def test_runtime_end_to_end_determinism():
    """Whole-runtime determinism through the syscall surface."""
    def run() -> dict[str, int]:
        rt = make_runtime(seed=99)
        fd = rt.qalloc(2, min_t2_us=200)
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=256)
        counts = rt.qmeasure(fd).counts()
        rt.qfree(fd)
        return counts
    assert run() == run()


def test_stale_lease_jobs_cancelled_at_dispatch():
    """Queued jobs whose lease staled after admission are cancelled."""
    mgr, sched, alice, _, la, _ = _two_proc_setup(seed=5)
    bell = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM,
                                      _shared_isa())
    sched.submit(la, bell, shots=4)
    mgr.recalibrate()                                # la goes STALE queued
    assert sched.run_pending() == 0                  # nothing executed
    s = sched.stats()
    assert s["jobs_cancelled"] == 1 and s["jobs_completed"] == 0
    assert len(la.ring) == 0


def test_classical_parameter_errors_are_valueerror_not_quantum_errno():
    """shots<1 etc. are caller bugs, not entries of the quantum table."""
    rt = make_runtime()
    fd = rt.qalloc(2)
    with pytest.raises(ValueError):
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=0)
    with pytest.raises(ValueError):
        rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, fidelity_floor=101)
    with pytest.raises(ValueError):
        rt.qalloc(0)
    with pytest.raises(ValueError):
        QLOSRuntime(n_pool_qubits=qcpu.MAX_QUBITS + 1)
    assert all(v == 0 for v in rt.stats()["jobs_rejected"].values())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
