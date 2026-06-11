"""QLOS v0.1 process model, lease manager, and QPU scheduler.

This module is builder C of the QLOS runtime (quantum-linux/qos/
QLOS-DESIGN-v0.1.md, section 8.4 -- BINDING contract): the kernel-services
analogue behind the four-call ``qalloc``/``qexec``/``qmeasure``/``qfree``
discipline of ``kernel-patches/qsyscall.h``. It implements:

* :class:`QProcess` -- the quantum process model of design doc section 3:
  a copyable classical execution context plus linear (move-only) qubit
  leases, with the NEW/READY/RUNNING/BLOCKED_ON_QPU/ZOMBIE lifecycle and
  fork/exec semantics that never duplicate a lease (no-cloning corollary,
  research doc docs/research/02-quantum-linux.md, Invariant 1 [Proven]).
* :class:`LeaseManager` -- exclusive linear-capability leases over a fixed
  physical qubit pool: one owner, never duplicated, no overcommit ever
  (-EBUSY on exhaustion; "no swap exists for quantum state" [Proven],
  research doc memory-model Invariant 3 / errno table).
* :class:`QPUScheduler` -- deadline-aware FIFO with coherence-budget
  admission control (design doc section 5): run-to-completion, one circuit
  at a time, no preemption ever (preemption requires saving quantum state,
  [Proven] forbidden by no-cloning and [Proven] lossy by measurement --
  research doc, Scheduler subsystem: EDF-style admission replaces CFS).

What is EMULATED vs what real hardware would do
-----------------------------------------------
Everything here is classical bookkeeping driving the ``qcpu.py`` dense-
statevector emulator. Each job executes on a FRESH ``qcpu.QCPU`` sized to
its lease ("statevector exclusivity"); shots start at |0...0> per
``QCPU.run_shots``, so lease state does not persist across jobs (design doc
limitation 3). The coherence budget is a classical cycle-count admission
policy, NOT a decoherence model [Theoretical]; real coherence windows are
per-shot and firmware-enforced [Demonstrated] (eQASM; QNodeOS) -- see design
doc section 5 and workflow Risk 3. On real hardware the device layer behind
:meth:`QPUScheduler.run_pending` becomes a QCX-attached QPU with DMA result
ring buffers (docs/research/03-hybrid-board.md) [Theoretical]; the
scheduling policy and errno contract survive that swap unchanged.

Errno contract: the exception classes defined here carry the exact negative
errno values of ``qsyscall.h`` (QERR_* aliases), always sourced from
Python's :mod:`errno` module -- values differ across platforms and are
never hard-coded (design doc section 4). The canonical definitions live in
this module so the qos dependency graph stays acyclic (qsyscalls imports
scheduler); ``qos/qsyscalls.py`` re-exports them under the binding section
8.3 names.

Import seam (design doc section 8): this module inserts the sibling
``emulator/`` directory on ``sys.path`` and imports ``qcpu`` as a plain
module, so it works both as a plain module (``import scheduler``) and via
the ``qos`` package facade.
"""

from __future__ import annotations

import collections
import copy
import enum
import errno as _errno
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable

import numpy as np

# -- import seam (design doc section 8): qcpu lives in ../emulator ----------
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "emulator"))
import qcpu  # noqa: E402  (path seam must run first)

# ---------------------------------------------------------------------------
# Constants mirrored from kernel-patches/qsyscall.h (names identical).
# Re-exported by qos/qsyscalls.py per the design doc section 8.3 contract;
# the conformance test parses the header's #defines and asserts equality.
# ---------------------------------------------------------------------------

#: ``struct qalloc_hints.topology`` values (qsyscall.h QTOPO_* block).
#: QTOPO_ANY is the only value the research doc's userspace flow uses; the
#: rest are header design extensions. The dense-statevector emulator is
#: effectively all-to-all coupled, so every topology request is satisfiable
#: and none fails with -EBUSY here (the header permits, not requires, that).
QTOPO_ANY: int = 0
QTOPO_LINE: int = 1
QTOPO_GRID: int = 2
QTOPO_ALL2ALL: int = 3

#: ``struct qexec_params.deadline`` best-effort value (qsyscall.h).
QDEADLINE_RELAXED: int = 0

#: ``struct qmeasure_result.flags`` bit: fewer shots than requested
#: (ring-buffer overflow dropped the oldest snapshots), qsyscall.h QMR_F_*.
QMR_F_PARTIAL: int = 1 << 0

#: Lease lifecycle states, ``struct qlease_desc.state`` (qsyscall.h).
QLEASE_STATE_LIVE: int = 1
QLEASE_STATE_CONSUMED: int = 2
QLEASE_STATE_STALE: int = 3

#: ``struct qlease_desc.vq_to_pq`` sizing (qsyscall.h): 2026 hardware pools
#: are 10^2-10^3 physical qubits. The emulated pool is further capped by
#: ``qcpu.MAX_QUBITS`` (24) -- an emulator-capacity limit, NOT the [Proven]
#: Theta(4**n/eps**2) tomography bound (design doc limitation 7).
QLEASE_MAX_QUBITS: int = 128

#: ``struct qlease_desc.flags`` bits (qsyscall.h QSET_F_*). These document
#: invariants enforced unconditionally, not requestable options: leases are
#: move-only (close-on-fork), never dup'd, never mmap'd [Proven]
#: (no-cloning theorem; measurement postulate -- research doc,
#: "Enforced invariants").
QSET_F_CLOFORK: int = 1 << 0
QSET_F_NODUP: int = 1 << 1
QSET_F_NOMMAP: int = 1 << 2

#: Provisional syscall numbers (qsyscall.h __NR_* block) -- design-artifact
#: placeholders above the Linux 6.12 LTS generic table, mirrored verbatim
#: for the conformance test. Module-level dunder names are legal Python and
#: not name-mangled outside class bodies.
__NR_qalloc: int = 463
__NR_qexec: int = 464
__NR_qmeasure: int = 465
__NR_qfree: int = 466

# ---------------------------------------------------------------------------
# Errno-style exceptions (design doc section 8.3; canonical definitions
# here, re-exported by qsyscalls -- see module docstring).
# ---------------------------------------------------------------------------


class QLOSError(OSError):
    """Base of the QLOS errno contract (design doc section 8.3).

    Mirrors the qsyscall.h error contract semantically: each concrete
    subclass carries the exact negative errno of one QERR_* alias, sourced
    from the stdlib :mod:`errno` module (never hard-coded -- values differ
    across platforms; design doc section 4).

    Attributes:
        qlos_errno: The negative errno (e.g. ``-errno.EBUSY``), matching
            the C shim's negative-int return convention.
        errno: The positive errno, per ordinary :class:`OSError` convention.
    """

    #: Negative errno of this failure class; overridden by subclasses.
    qlos_errno: ClassVar[int] = 0

    def __init__(self, message: str) -> None:
        super().__init__(-self.qlos_errno, message)


class PoolExhaustedError(QLOSError):
    """-EBUSY / QERR_POOL_EXHAUSTED: qubit pool exhausted on ``qalloc``.

    No overcommit exists because no swap exists [Proven]: paging out a
    qubit would be tomography over copies no-cloning forbids, at
    Theta(4**n/eps**2) destructive shots (qsyscall.h errno table; research
    doc, memory-model Invariant 1 + 3).
    """

    qlos_errno: ClassVar[int] = -_errno.EBUSY


class CoherenceBudgetError(QLOSError):
    """-ETIME / QERR_COHERENCE_BUDGET: circuit exceeds the coherence budget.

    Raised at ``qexec`` submit when the static per-shot cycle estimate
    exceeds the lease's remaining budget or the job's own deadline budget
    (qsyscall.h errno table: "circuit depth exceeds the coherence/QEC
    budget declared by the device"). The budget is a [Theoretical]
    classical-side admission policy, not a decoherence model (design doc
    section 5).
    """

    qlos_errno: ClassVar[int] = -_errno.ETIME


class VerifierRejectError(QLOSError):
    """-ENOEXEC / QERR_VERIFIER_REJECT: static verifier rejection.

    Gate on an unleased qubit, use-after-measure without RESET, or a
    malformed program -- the quantum analogue of W^X enforcement (research
    doc, errno table; rules in isa-spec/QISA-v0.1.yaml ``verifier_rules``).
    Wraps the emulator's own :class:`qcpu.QISAVerifierError`.
    """

    qlos_errno: ClassVar[int] = -_errno.ENOEXEC


class FidelityFloorError(QLOSError):
    """-EIO / QERR_FIDELITY_FLOOR: readout below the requested floor.

    ``qmeasure`` fails instead of returning data; the lease is still
    consumed -- the destructive readout happened, it was just bad
    (qsyscall.h errno table: calibration drift; design doc section 4).
    """

    qlos_errno: ClassVar[int] = -_errno.EIO


class LeaseStaleError(QLOSError):
    """-ESTALE / QERR_LEASE_STALE: placement invalidated by recalibration.

    The caller must re-``qalloc`` (qsyscall.h errno table). Per design doc
    section 3 rule 4, only ``qfree`` remains valid on a STALE lease.
    """

    qlos_errno: ClassVar[int] = -_errno.ESTALE


class PhysUndefinedError(QLOSError):
    """-EPERM / QERR_PHYS_UNDEFINED: copying or non-destructive observation.

    ``dup()`` of a qset fd, and reuse of a CONSUMED lease (second
    ``qmeasure``, or ``qexec`` after ``qmeasure``), are the same violation
    class: extracting more than one use from a use-at-most-once linear
    capability -- physically undefined [Proven] (no-cloning, Wootters &
    Zurek 1982; measurement postulate). The consumed-lease mapping to
    -EPERM is a v0.1 ABI completion made by the design doc (section 3
    rule 3).
    """

    qlos_errno: ClassVar[int] = -_errno.EPERM


class BadDescriptorError(QLOSError):
    """-EBADF: unknown qset fd -- ordinary POSIX, deliberately NOT in the
    header's quantum errno table (design doc section 4)."""

    qlos_errno: ClassVar[int] = -_errno.EBADF


# ---------------------------------------------------------------------------
# Cost table (design doc section 5) -- [Theoretical] policy parameters.
# ---------------------------------------------------------------------------

#: Virtual-clock cycles per microsecond of declared coherence/deadline.
CYCLES_PER_US: int = 10
#: Per-instruction cycle costs. Ratios loosely follow superconducting
#: gate-vs-readout durations but are [Theoretical] policy parameters, not
#: hardware claims (the QWAIT counter is not a timing model -- workflow
#: Risk 3). FMR/BRN cost 0: classical feed-forward lives in control
#: firmware on real hardware [Demonstrated] (eQASM; QNodeOS).
COST_1Q: int = 1
COST_2Q: int = 3
COST_MEASURE: int = 10
COST_RESET: int = 12

_1Q_OPCODES = frozenset({"H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ"})
_2Q_OPCODES = frozenset({"CNOT", "CZ"})


class QProcState(enum.Enum):
    """QProcess lifecycle states (design doc section 3)."""

    NEW = "NEW"                       # created; no leases held
    READY = "READY"                   # holds >=1 lease, no jobs in flight
    RUNNING = "RUNNING"               # transient; inside any QLOS call
    BLOCKED_ON_QPU = "BLOCKED_ON_QPU"  # submitted jobs not yet complete
    ZOMBIE = "ZOMBIE"                 # exited; leases revoked, stats kept


@runtime_checkable
class QObjLike(Protocol):
    """Structural type of an assembled QOBJ (design doc section 6.2).

    ``toolchain/qas.QObj`` satisfies this protocol; so does the runtime's
    internal fallback used when the toolchain is not yet importable. The
    scheduler needs only the decoded instruction stream (for the static
    cost estimate) and a :class:`qcpu.Program` view (for verify + run).
    """

    instructions: tuple[qcpu.Instruction, ...]

    def to_program(self) -> qcpu.Program:
        """Return the program for ``QCPU.verify`` / ``QCPU.run_shots``."""
        ...


def estimate_cycles(qobj: QObjLike) -> int:
    """Static per-shot cycle cost of ``qobj`` (design doc section 5 table).

    Straight-line sum over the assembled instruction stream, in program
    order and ignoring branches -- instructions a ``BRN`` may skip at run
    time are still charged, making the estimate conservative in exactly
    the way the emulator's verifier is (``qcpu.QCPU.verify`` checks in
    program order, "conservative w.r.t. branches"). ``QWAIT`` charges its
    immediate; ``FMR``/``BRN`` charge 0 (firmware-resident feed-forward,
    [Demonstrated] eQASM/QNodeOS).

    This is admission-policy arithmetic, not physics [Theoretical]: real
    coherence windows are per-shot and firmware-enforced [Demonstrated].

    Args:
        qobj: Assembled object (anything satisfying :class:`QObjLike`).

    Returns:
        Estimated cycles for ONE shot of the program.
    """
    total = 0
    for ins in qobj.instructions:
        op = ins.opcode
        if op in _1Q_OPCODES:
            total += COST_1Q
        elif op in _2Q_OPCODES:
            total += COST_2Q
        elif op == "MEASURE":
            total += COST_MEASURE
        elif op == "RESET":
            total += COST_RESET
        elif op == "QWAIT":
            total += int(ins.operands[0])
        # FMR / BRN: 0 cycles (classical feed-forward, firmware-resident).
    return total


# ---------------------------------------------------------------------------
# Lease record
# ---------------------------------------------------------------------------


@dataclass
class Lease:
    """Kernel-side lease record -- the Python view of ``struct qlease_desc``.

    A lease is a LINEAR capability (research doc, QISA memory-model design
    consequence): one owner, ownership moves and never copies, explicitly
    consumed by measurement. The per-lease ``ring`` is the bounded
    measurement ring buffer of design doc section 3 -- the only
    quantum->classical channel, mirroring the hybrid-board doc's DMA result
    ring buffers [Theoretical]. Everything stored here is CLASSICAL
    metadata; no amplitude ever lives in a Lease.

    Attributes:
        lease_id: Unique capability serial (``qlease_desc.lease_id``).
        owner_pid: Pid of the single owning :class:`QProcess`.
        n_qubits: Leased qubit count (virtual ids q0..q[n-1]).
        vq_to_pq: Virtual->physical qubit table (``qlease_desc.vq_to_pq``).
        cal_epoch: Calibration generation at placement time.
        state: ``QLEASE_STATE_LIVE`` / ``_CONSUMED`` / ``_STALE``.
        coherence_budget_cycles: Total admission budget granted at qalloc.
        coherence_remaining_cycles: Budget not yet reserved by admitted jobs.
        ring: Bounded deque of per-shot shadow snapshots (oldest dropped on
            overflow -> QMR_F_PARTIAL at qmeasure).
    """

    lease_id: int
    owner_pid: int
    n_qubits: int
    vq_to_pq: tuple[int, ...]
    cal_epoch: int
    state: int
    coherence_budget_cycles: int
    coherence_remaining_cycles: int
    ring: collections.deque = field(default_factory=collections.deque)


# ---------------------------------------------------------------------------
# QProcess
# ---------------------------------------------------------------------------

#: Per-process / global statistics template. "Rejects" is keyed by errno
#: NAME (not number) so reports stay platform-portable.
_REJECT_KEYS = ("ENOEXEC", "ETIME", "ESTALE", "EPERM")


def _fresh_stats() -> dict[str, Any]:
    """New zeroed stats dict (shared shape for QProcess and scheduler)."""
    return {
        "jobs_submitted": 0,
        "jobs_completed": 0,
        "jobs_rejected": {k: 0 for k in _REJECT_KEYS},
        "jobs_cancelled": 0,
        "deadline_misses": 0,
        "gate_counts": {},
        "two_qubit_gate_count": 0,
        "measure_count": 0,
        "shot_count": 0,
    }


class QProcess:
    """A quantum process (design doc section 3).

    = ordinary, copyable classical context (pid, name, stats -- legal to
    copy precisely because it is classical) + qubit leases (linear
    capabilities: one owner, never duplicated) + submitted circuits
    (run-to-completion, never preempted) + per-lease measurement rings.

    Args:
        pid: Process id.
        name: Image name (classical metadata).
    """

    def __init__(self, pid: int, name: str = "") -> None:
        self.pid: int = pid
        self.name: str = name
        self.state: QProcState = QProcState.NEW
        self.leases: dict[int, Lease] = {}
        #: Per-process stats (assignment: gate counts, shots, rejects);
        #: same key shape as the global :meth:`QPUScheduler.stats`.
        self.stats: dict[str, Any] = _fresh_stats()
        # Back-reference set by LeaseManager.allocate so exec_image()/exit()
        # can revoke leases without the caller threading the manager
        # through; private -- not part of the binding contract.
        self._lease_mgr: "LeaseManager | None" = None

    def fork(self, child_pid: int) -> "QProcess":
        """fork(): copy the CLASSICAL context only; the child gets NO leases.

        Qset capabilities are close-on-fork (``QSET_F_CLOFORK``): the
        parent keeps them, the child starts in ``NEW`` with an empty lease
        table. A duplicated lease would copy live quantum state --
        physically undefined [Proven] (no-cloning, Wootters & Zurek 1982;
        research doc Invariant 1; design doc section 3). Copying the
        classical half (name, stats) is legal precisely because it is
        classical.

        Args:
            child_pid: Pid for the child process.

        Returns:
            The child :class:`QProcess` (state ``NEW``, no leases).
        """
        child = QProcess(child_pid, name=self.name)
        child.stats = copy.deepcopy(self.stats)
        child._lease_mgr = self._lease_mgr
        return child

    def exec_image(self, name: str) -> None:
        """exec(): replace the classical image; ALL leases are revoked.

        Revocation is ``qfree`` semantics -- RESET + return to pool: it
        destroys state, never copies it, and is therefore always
        physically allowed (research doc: qubit handles behave like
        ``O_CLOEXEC`` fds; design doc section 3). The process continues
        with the new image name, lease-less (state ``NEW``).

        Args:
            name: The replacement image name.
        """
        self._revoke_all_leases()
        self.name = name
        self.state = QProcState.NEW

    def exit(self) -> None:
        """exit(): revoke all leases (RESET + return to pool) -> ZOMBIE.

        Classical stats are retained for reaping (design doc section 3);
        they are copyable classical data, unlike the revoked quantum
        resources.
        """
        self._revoke_all_leases()
        self.state = QProcState.ZOMBIE

    def _revoke_all_leases(self) -> None:
        """Release every held lease through the owning LeaseManager."""
        for lease in list(self.leases.values()):
            if self._lease_mgr is not None:
                self._lease_mgr.release(lease)
            else:  # un-managed process: just drop the (classical) records
                self.leases.pop(lease.lease_id, None)

    def __repr__(self) -> str:  # pragma: no cover -- debugging aid
        return (f"QProcess(pid={self.pid}, name={self.name!r}, "
                f"state={self.state.value}, leases={sorted(self.leases)})")


# ---------------------------------------------------------------------------
# LeaseManager
# ---------------------------------------------------------------------------


class LeaseManager:
    """Exclusive linear-capability leases over a fixed physical qubit pool.

    The qubit allocator of the research doc's subsystem audit (class B:
    "fixed heterogeneous pool, calibration-aware placement, linear-resource
    accounting; no overcommit"). Spatial accounting only: leases partition
    the pool; circuit execution is serialized separately by
    :class:`QPUScheduler` (design doc section 5, "QPU multiplexing").

    Emulation honesty: the pool is homogeneous and all-to-all here, so
    placement is trivially lowest-free-index and topology hints are
    recorded but never constrain placement; real allocation is
    calibration-aware and fidelity-critical [Demonstrated] (QOS placement,
    OSDI '25; research doc, memory-model Invariant 5 row).

    Args:
        n_pool_qubits: Physical pool size; capped by ``qcpu.MAX_QUBITS``
            (emulator capacity, design doc limitation 7) and
            ``QLEASE_MAX_QUBITS`` (header ABI cap).
        default_budget_cycles: Coherence budget granted when ``qalloc``
            gives no ``min_t2_us`` hint.
        ring_capacity_shots: Bound of each lease's measurement ring buffer.
    """

    def __init__(self, n_pool_qubits: int, *,
                 default_budget_cycles: int = 10_000,
                 ring_capacity_shots: int = 65_536) -> None:
        cap = min(qcpu.MAX_QUBITS, QLEASE_MAX_QUBITS)
        if not 1 <= n_pool_qubits <= cap:
            raise ValueError(
                f"n_pool_qubits={n_pool_qubits} out of range 1..{cap}: the "
                f"emulated pool is capped by qcpu.MAX_QUBITS="
                f"{qcpu.MAX_QUBITS} (dense-statevector capacity, NOT the "
                "[Proven] tomography bound) and QLEASE_MAX_QUBITS="
                f"{QLEASE_MAX_QUBITS} (qsyscall.h ABI cap)"
            )
        if default_budget_cycles < 1:
            raise ValueError("default_budget_cycles must be >= 1")
        if ring_capacity_shots < 1:
            raise ValueError("ring_capacity_shots must be >= 1")
        self.n_pool_qubits: int = n_pool_qubits
        self.default_budget_cycles: int = default_budget_cycles
        self.ring_capacity_shots: int = ring_capacity_shots
        self.cal_epoch: int = 1
        # Free physical qubits, kept sorted for deterministic placement.
        self._free_pq: list[int] = list(range(n_pool_qubits))
        self._leases: dict[int, Lease] = {}     # live leases by lease_id
        self._procs: dict[int, QProcess] = {}   # pid -> process registry
        self._next_lease_id: int = 1

    # -- allocation ---------------------------------------------------------

    def allocate(self, proc: QProcess, n_qubits: int, *,
                 min_t2_us: int = 0,
                 topology: int = QTOPO_ANY) -> Lease:
        """Lease ``n_qubits`` physical qubits exclusively to ``proc``.

        Mirrors ``qalloc`` (qsyscall.h ``__NR_qalloc`` 463) at the
        kernel-record level. NEVER blocks and never overcommits: there is
        no swap to wait on [Proven] (research doc errno table; design doc
        section 4 -- "fails fast").

        The ``min_t2_us`` hint (``struct qalloc_hints.min_t2_us``) sets the
        lease's coherence budget to ``min_t2_us * CYCLES_PER_US``; without
        it the manager's default applies. This converts the header's
        calibration-aware-placement hint into the [Theoretical] admission
        budget of design doc section 5 -- the emulator has no real T2.

        Args:
            proc: The single owning process (linear capability).
            n_qubits: Number of qubits to lease (>= 1).
            min_t2_us: Minimum acceptable T2, microseconds (hint).
            topology: ``QTOPO_*`` connectivity requirement; recorded only
                (the emulator is all-to-all, every request is satisfiable).

        Returns:
            The new LIVE :class:`Lease`.

        Raises:
            PoolExhaustedError: -EBUSY when fewer than ``n_qubits`` free
                physical qubits remain (no overcommit, ever).
            ValueError: On non-positive ``n_qubits`` / negative hints
                (classical parameter errors, outside the quantum errno
                table).
        """
        if n_qubits < 1:
            raise ValueError(f"n_qubits must be >= 1, got {n_qubits}")
        if min_t2_us < 0:
            raise ValueError(f"min_t2_us must be >= 0, got {min_t2_us}")
        if topology not in (QTOPO_ANY, QTOPO_LINE, QTOPO_GRID,
                            QTOPO_ALL2ALL):
            raise ValueError(f"unknown topology hint {topology}")
        if proc.state is QProcState.ZOMBIE:
            raise ValueError(f"pid {proc.pid} is a ZOMBIE; cannot allocate")
        if n_qubits > len(self._free_pq):
            raise PoolExhaustedError(
                f"qubit pool exhausted: requested {n_qubits}, "
                f"{len(self._free_pq)}/{self.n_pool_qubits} free -- no "
                "overcommit exists because no swap exists [Proven]"
            )
        pq = tuple(self._free_pq[:n_qubits])
        del self._free_pq[:n_qubits]
        budget = (min_t2_us * CYCLES_PER_US if min_t2_us > 0
                  else self.default_budget_cycles)
        lease = Lease(
            lease_id=self._next_lease_id,
            owner_pid=proc.pid,
            n_qubits=n_qubits,
            vq_to_pq=pq,
            cal_epoch=self.cal_epoch,
            state=QLEASE_STATE_LIVE,
            coherence_budget_cycles=budget,
            coherence_remaining_cycles=budget,
            ring=collections.deque(maxlen=self.ring_capacity_shots),
        )
        self._next_lease_id += 1
        self._leases[lease.lease_id] = lease
        self._procs[proc.pid] = proc
        proc._lease_mgr = self
        proc.leases[lease.lease_id] = lease
        if proc.state is QProcState.NEW:
            proc.state = QProcState.READY
        return lease

    def release(self, lease: Lease) -> None:
        """Release ``lease``: RESET semantics + return qubits to the pool.

        Mirrors the resource half of ``qfree`` (qsyscall.h ``__NR_qfree``
        466): always succeeds, even on STALE/CONSUMED leases -- revocation
        destroys state, never copies it, and is always physically allowed
        (research doc, VFS section: ``close()`` = RESET + free). The RESET
        is a documentation-level no-op here because lease state never
        persists between jobs in the emulator (each shot starts at
        |0...0>, design doc limitation 3); on hardware it is the active
        |0> preparation (measure + conditional X).

        Args:
            lease: A live lease previously returned by :meth:`allocate`.

        Raises:
            ValueError: If the lease is unknown or already released
                (double-free is a caller bug, not a quantum errno case).
        """
        if self._leases.pop(lease.lease_id, None) is None:
            raise ValueError(
                f"lease {lease.lease_id} unknown or already released")
        self._free_pq.extend(lease.vq_to_pq)
        self._free_pq.sort()
        lease.ring.clear()
        owner = self._procs.get(lease.owner_pid)
        if owner is not None:
            owner.leases.pop(lease.lease_id, None)
            if (owner.state is not QProcState.ZOMBIE
                    and not owner.leases):
                owner.state = QProcState.NEW  # back to lease-less (section 3)

    def recalibrate(self) -> int:
        """Bump the calibration epoch; every LIVE lease goes STALE.

        The -ESTALE test seam (design doc section 4; workflow Risk 6:
        drift handling deferred -- this stubs the recalibration event).
        Real devices recalibrate because per-qubit fidelity drifts
        hour-to-hour [Demonstrated] (research doc, device-driver section);
        the emulator has no drift, so this is policy-only.

        Returns:
            The new calibration epoch.
        """
        self.cal_epoch += 1
        for lease in self._leases.values():
            if lease.state == QLEASE_STATE_LIVE:
                lease.state = QLEASE_STATE_STALE
        return self.cal_epoch

    def free_qubits(self) -> int:
        """Number of unleased physical qubits remaining in the pool."""
        return len(self._free_pq)

    def owner_of(self, lease: Lease) -> QProcess | None:
        """The registered owning process of ``lease``, if any."""
        return self._procs.get(lease.owner_pid)


# ---------------------------------------------------------------------------
# QPUScheduler
# ---------------------------------------------------------------------------


@dataclass
class _Job:
    """One admitted, not-yet-executed circuit submission (private)."""

    job_id: int
    lease: Lease
    program: qcpu.Program
    shots: int
    fidelity_floor: int
    deadline_us: int
    abs_deadline_cycles: int | None  # None == QDEADLINE_RELAXED
    est_cycles: int                  # reserved per-shot estimate
    seed: int | None                 # per-job QCPU seed (determinism)
    submit_seq: int                  # FIFO tiebreak


class QPUScheduler:
    """Deadline-aware FIFO with coherence-budget admission control.

    Design doc section 5, in full: run-to-completion, NO preemption ever
    (preempting a running circuit requires saving quantum state --
    [Proven] forbidden by no-cloning and [Proven] lossy by measurement;
    research doc, Scheduler subsystem), exactly one circuit executing at a
    time (statevector exclusivity today; the single-QPU pipeline on
    hardware). Leases time-share the QPU: :class:`LeaseManager` partitions
    the qubit pool spatially, this class serializes execution temporally.
    QOS-style spatial multiplexing of concurrent circuits [Demonstrated]
    (Giortamis et al., OSDI '25) is deliberately NOT modeled (design doc
    limitation 2).

    Dispatch order: finite-deadline jobs first, by ascending absolute
    deadline (ties: submission order); ``QDEADLINE_RELAXED`` jobs follow in
    FIFO order. Deadlines are soft in v0.1: a miss increments
    ``stats()["deadline_misses"]`` and the job still runs.

    Args:
        lease_mgr: The lease manager whose leases jobs run against.
        seed: Master RNG seed. Each admitted job is assigned its own
            derived seed AT SUBMIT, so a given submission sequence replays
            bit-identically regardless of when ``run_pending`` happens --
            the multi-process multiplexing determinism contract.
        isa: Optional pre-loaded :class:`qcpu.ISA` shared by the verifier
            and every per-job QCPU (avoids re-parsing the YAML per job).
    """

    def __init__(self, lease_mgr: LeaseManager, *,
                 seed: int | None = None,
                 isa: qcpu.ISA | None = None) -> None:
        self.lease_mgr: LeaseManager = lease_mgr
        self.isa: qcpu.ISA = isa if isa is not None else qcpu.ISA()
        self._seed_seq: np.random.SeedSequence | None = (
            None if seed is None else np.random.SeedSequence(seed))
        self._queue: list[_Job] = []
        self._next_job_id: int = 0
        self._submit_seq: int = 0
        self.virtual_now_cycles: int = 0
        self._stats: dict[str, Any] = _fresh_stats()

    # -- submission (verify -> admit -> reserve -> enqueue) ------------------

    def submit(self, lease: Lease, qobj: QObjLike, *, shots: int = 1,
               deadline_us: int = 0, fidelity_floor: int = 0) -> int:
        """Admit one circuit for deferred run-to-completion execution.

        The scheduler half of ``qexec`` (qsyscall.h ``__NR_qexec`` 464 /
        ``QPU_IOC_QEXEC``, ``struct qexec_submit`` + ``qexec_params``).
        NEVER blocks: verification and admission happen synchronously,
        execution is deferred to :meth:`run_pending` -- the runtime
        analogue of the header's async submit with io_uring CQE completion
        (research doc, syscall table).

        Pipeline, in the design doc section 8.4 binding order:

        1. **verify** -- the submitted object is untrusted input, exactly
           as ELF is: re-verified with the emulator's own static verifier
           (``qcpu.QCPU.verify`` on a throwaway QCPU sized to the LEASE,
           so the lease-relative no-gate-on-unleased-qubit rule is checked
           against the real lease) -> :class:`VerifierRejectError`
           (-ENOEXEC).
        2. **admit** -- CONSUMED lease -> :class:`PhysUndefinedError`
           (-EPERM, use of a consumed linear capability, section 3 rule
           3); STALE lease -> :class:`LeaseStaleError` (-ESTALE);
           per-shot :func:`estimate_cycles` over the lease's remaining
           coherence budget, or over the job's own ``deadline_us`` budget,
           -> :class:`CoherenceBudgetError` (-ETIME).
        3. **reserve** -- the estimate is deducted from the lease budget at
           submit (conservative EDF-style admission).
        4. **enqueue** -- with absolute deadline ``virtual_now_cycles +
           deadline_us * CYCLES_PER_US`` when ``deadline_us > 0``.

        Args:
            lease: The owning lease (linear capability).
            qobj: Assembled object satisfying :class:`QObjLike`.
            shots: Statistically independent trials (>= 1) -- NOT
                cooperating threads (research doc, mapping table).
            deadline_us: 0 = ``QDEADLINE_RELAXED``; else relative soft
                deadline in microseconds.
            fidelity_floor: Percent; readout below it fails the eventual
                ``qmeasure`` with -EIO.

        Returns:
            The job id (>= 0). The C ABI's ``qexec`` returns 0; returning
            the id is information-compatible (design doc section 8.3).

        Raises:
            VerifierRejectError: -ENOEXEC (static verifier rejection).
            PhysUndefinedError: -EPERM (submission on a CONSUMED lease).
            LeaseStaleError: -ESTALE (placement invalidated; re-qalloc).
            CoherenceBudgetError: -ETIME (estimate exceeds remaining lease
                budget or the job's own deadline budget).
            ValueError: On classical parameter errors (shots < 1,
                negative deadline, fidelity_floor outside 0..100).
        """
        if shots < 1:
            raise ValueError(f"shots must be >= 1, got {shots}")
        if deadline_us < 0:
            raise ValueError(f"deadline_us must be >= 0, got {deadline_us}")
        if not 0 <= fidelity_floor <= 100:
            raise ValueError(
                f"fidelity_floor must be 0..100, got {fidelity_floor}")
        owner = self.lease_mgr.owner_of(lease)

        # 1. verify (defense in depth: object files are untrusted input).
        try:
            program = qobj.to_program()
            qcpu.QCPU(n_qubits=lease.n_qubits, isa=self.isa).verify(program)
        except qcpu.QISAVerifierError as exc:
            self._reject("ENOEXEC", owner)
            raise VerifierRejectError(
                f"verifier rejected program: {exc}") from exc

        # 2. admit.
        if lease.state == QLEASE_STATE_CONSUMED:
            self._reject("EPERM", owner)
            raise PhysUndefinedError(
                f"lease {lease.lease_id} already CONSUMED: qexec after "
                "qmeasure reuses a use-at-most-once capability [Proven]")
        if lease.state == QLEASE_STATE_STALE:
            self._reject("ESTALE", owner)
            raise LeaseStaleError(
                f"lease {lease.lease_id} staled by recalibration (epoch "
                f"{lease.cal_epoch} < device epoch "
                f"{self.lease_mgr.cal_epoch}); re-qalloc required")
        est = estimate_cycles(qobj)
        if est > lease.coherence_remaining_cycles:
            self._reject("ETIME", owner)
            raise CoherenceBudgetError(
                f"estimated {est} cycles/shot exceeds remaining coherence "
                f"budget {lease.coherence_remaining_cycles} of lease "
                f"{lease.lease_id} (circuit depth exceeds the "
                "coherence/QEC budget declared by the device)")
        if deadline_us > 0 and est > deadline_us * CYCLES_PER_US:
            self._reject("ETIME", owner)
            raise CoherenceBudgetError(
                f"estimated {est} cycles/shot exceeds the job's own "
                f"deadline budget {deadline_us * CYCLES_PER_US} cycles "
                f"({deadline_us} us)")

        # 3. reserve (conservative EDF-style admission).
        lease.coherence_remaining_cycles -= est

        # 4. enqueue.
        job = _Job(
            job_id=self._next_job_id,
            lease=lease,
            program=program,
            shots=shots,
            fidelity_floor=fidelity_floor,
            deadline_us=deadline_us,
            abs_deadline_cycles=(
                self.virtual_now_cycles + deadline_us * CYCLES_PER_US
                if deadline_us > 0 else None),
            est_cycles=est,
            seed=self._spawn_seed(),
            submit_seq=self._submit_seq,
        )
        self._next_job_id += 1
        self._submit_seq += 1
        self._queue.append(job)
        self._stats["jobs_submitted"] += 1
        if owner is not None:
            owner.stats["jobs_submitted"] += 1
            owner.state = QProcState.BLOCKED_ON_QPU
        return job.job_id

    def _spawn_seed(self) -> int | None:
        """Derive a per-job seed from the master SeedSequence (at submit)."""
        if self._seed_seq is None:
            return None
        (child,) = self._seed_seq.spawn(1)
        return int(child.generate_state(1)[0])

    def _reject(self, key: str, owner: QProcess | None) -> None:
        """Record a rejected submission in global + per-process stats."""
        self._stats["jobs_rejected"][key] += 1
        if owner is not None:
            owner.stats["jobs_rejected"][key] += 1

    # -- execution ------------------------------------------------------------

    def run_pending(self, max_jobs: int | None = None) -> int:
        """Execute queued jobs per the section 5 dispatch order.

        One circuit at a time, run-to-completion (no preemption EVER --
        [Proven] no-cloning + measurement, research doc Scheduler
        subsystem). Each job executes on a FRESH ``qcpu.QCPU`` sized to
        its lease (statevector exclusivity; every shot starts at |0...0>
        per ``QCPU.run_shots``); the per-shot shadow snapshots are appended
        to the lease's measurement ring buffer -- the runtime analogue of
        the hybrid-board doc's DMA result rings [Theoretical].

        Jobs whose lease went STALE after admission are cancelled at
        dispatch (placement is invalid; design doc section 3 rule 4 leaves
        only ``qfree`` valid on a STALE lease) -- a v0.1 policy completion,
        counted under ``jobs_cancelled``.

        Args:
            max_jobs: Execute at most this many jobs (None = drain).

        Returns:
            Number of jobs actually executed (cancellations excluded).
        """
        executed = 0
        while self._queue and (max_jobs is None or executed < max_jobs):
            job = self._pop_next_job()
            owner = self.lease_mgr.owner_of(job.lease)
            if job.lease.state == QLEASE_STATE_STALE:
                self._stats["jobs_cancelled"] += 1
                if owner is not None:
                    owner.stats["jobs_cancelled"] += 1
                self._settle_owner_state(owner)
                continue
            cpu = qcpu.QCPU(n_qubits=job.lease.n_qubits, seed=job.seed,
                            isa=self.isa)
            snapshots = cpu.run_shots(job.program, job.shots)
            job.lease.ring.extend(snapshots)  # bounded: oldest dropped
            self.virtual_now_cycles += job.est_cycles
            if (job.abs_deadline_cycles is not None
                    and self.virtual_now_cycles > job.abs_deadline_cycles):
                self._stats["deadline_misses"] += 1
                if owner is not None:
                    owner.stats["deadline_misses"] += 1
            self._fold_stats(self._stats, cpu)
            self._stats["jobs_completed"] += 1
            if owner is not None:
                self._fold_stats(owner.stats, cpu)
                owner.stats["jobs_completed"] += 1
            self._settle_owner_state(owner)
            executed += 1
        return executed

    def _pop_next_job(self) -> _Job:
        """Remove and return the next job per the dispatch order."""
        deadline_jobs = [j for j in self._queue
                         if j.abs_deadline_cycles is not None]
        if deadline_jobs:
            job = min(deadline_jobs,
                      key=lambda j: (j.abs_deadline_cycles, j.submit_seq))
        else:
            job = min(self._queue, key=lambda j: j.submit_seq)  # FIFO
        self._queue.remove(job)
        return job

    def _settle_owner_state(self, owner: QProcess | None) -> None:
        """BLOCKED_ON_QPU -> READY once a process has no jobs in flight."""
        if owner is None or owner.state is not QProcState.BLOCKED_ON_QPU:
            return
        if not any(j.lease.owner_pid == owner.pid for j in self._queue):
            owner.state = QProcState.READY

    @staticmethod
    def _fold_stats(into: dict[str, Any], cpu: qcpu.QCPU) -> None:
        """Accumulate one finished QCPU's counters into a stats dict."""
        s = cpu.stats()
        for op, n in s["gate_counts"].items():
            into["gate_counts"][op] = into["gate_counts"].get(op, 0) + n
        into["two_qubit_gate_count"] += s["two_qubit_gate_count"]
        into["measure_count"] += s["measure_count"]
        into["shot_count"] += s["shot_count"]

    # -- queue maintenance ------------------------------------------------------

    def pending_jobs(self, lease: Lease | None = None) -> int:
        """Count queued (not yet executed) jobs, optionally per lease."""
        if lease is None:
            return len(self._queue)
        return sum(1 for j in self._queue
                   if j.lease.lease_id == lease.lease_id)

    def max_pending_fidelity_floor(self, lease: Lease) -> int:
        """Highest fidelity_floor among queued jobs of ``lease`` (0 if none)."""
        floors = [j.fidelity_floor for j in self._queue
                  if j.lease.lease_id == lease.lease_id]
        return max(floors, default=0)

    def cancel_lease(self, lease: Lease) -> int:
        """Cancel every still-queued job of ``lease`` (the qfree path).

        Mirrors ``qfree``'s "cancels the lease's still-queued jobs"
        clause (design doc section 4 table). Cancellation destroys only
        classical queue records -- always physically allowed.

        Args:
            lease: The lease being freed.

        Returns:
            Number of jobs cancelled.
        """
        kept: list[_Job] = []
        cancelled = 0
        owner = self.lease_mgr.owner_of(lease)
        for job in self._queue:
            if job.lease.lease_id == lease.lease_id:
                cancelled += 1
            else:
                kept.append(job)
        self._queue = kept
        self._stats["jobs_cancelled"] += cancelled
        if owner is not None and cancelled:
            owner.stats["jobs_cancelled"] += cancelled
        self._settle_owner_state(owner)
        return cancelled

    # -- reporting ----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Global scheduler statistics (design doc section 8.4 binding keys).

        Keys: ``jobs_submitted``, ``jobs_completed``, ``jobs_rejected``
        (dict by errno name), ``jobs_cancelled``, ``deadline_misses``,
        ``virtual_now_cycles``, ``gate_counts`` (aggregated),
        ``two_qubit_gate_count``, ``measure_count``, ``shot_count``.

        Returns:
            A copy safe for the caller to mutate.
        """
        out = copy.deepcopy(self._stats)
        out["virtual_now_cycles"] = self.virtual_now_cycles
        return out


def _demo() -> None:
    """Two processes time-sharing the QPU under deadline-aware FIFO."""
    import qsyscalls  # local sibling; provides the assemble fallback

    mgr = LeaseManager(8)
    sched = QPUScheduler(mgr, seed=7)
    alice, bob = QProcess(100, "alice"), QProcess(101, "bob")
    la = mgr.allocate(alice, 2, min_t2_us=200)
    lb = mgr.allocate(bob, 2, min_t2_us=200)
    qobj = qsyscalls._assemble_source(qcpu.BELL_UNCORRECTED_ASM, sched.isa)
    sched.submit(la, qobj, shots=64, deadline_us=500)
    sched.submit(lb, qobj, shots=64)  # QDEADLINE_RELAXED
    print(f"executed {sched.run_pending()} jobs")
    print(f"alice ring: {len(la.ring)} shots, bob ring: {len(lb.ring)} shots")
    print(f"global stats: {sched.stats()}")


if __name__ == "__main__":
    _demo()
