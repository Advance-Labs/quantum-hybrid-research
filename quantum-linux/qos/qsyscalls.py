"""QLOS v0.1 user-space syscall shim -- the four-call quantum ABI in Python.

Builder B of the QLOS runtime (quantum-linux/qos/QLOS-DESIGN-v0.1.md,
sections 4 and 8.3 -- BINDING contract). :class:`QLOSRuntime` mirrors the
``qalloc``/``qexec``/``qmeasure``/``qfree`` interface of
``kernel-patches/qsyscall.h`` SEMANTICALLY: same names, same struct fields
as keyword arguments / result fields, same errnos -- always sourced from
Python's :mod:`errno` module, never hard-coded (design doc section 4).
The runtime composes one root :class:`scheduler.QProcess` (pid 1) with a
:class:`scheduler.LeaseManager` and :class:`scheduler.QPUScheduler`;
multi-process scenarios use those classes directly (design doc section
8.3 notes).

What is EMULATED vs what real hardware would do
-----------------------------------------------
Today the device layer is the ``qcpu.py`` dense statevector emulator
(<= 24 qubits, an emulator-capacity limit -- NOT the [Proven]
Theta(4**n/eps**2) tomography bound; design doc limitation 7); tomorrow it
is ``/dev/qpu0`` over QCX with the SAME four-call ABI [Theoretical]
(docs/research/03-hybrid-board.md; design doc section 2). The architecture
invariant holds throughout (research doc
docs/research/02-quantum-linux.md, userspace-flow section): quantum state
NEVER crosses this boundary -- only its classical shadow does (measurement
bits, histograms, lease metadata flow up; only verified programs flow
down). The backend is noiseless, so ``fidelity_est`` is the constant
``readout_fidelity`` knob -- without it the -EIO path would be unreachable
(design doc limitation 1); real readout fidelity drifts [Demonstrated].

Toolchain seam: ``qexec`` accepting assembly text delegates to
``toolchain/qas.assemble`` when that module is importable (design doc
section 8.3); until builder A lands it, an internal fallback builds an
equivalent QObj-shaped object via ``qcpu.assemble`` -- sound because qas
itself is REQUIRED to delegate parsing to ``qcpu.assemble`` (design doc
section 6.3, "the toolchain adds no syntax").

Import seam (design doc section 8): plain-module imports behind
``sys.path`` insertion of the sibling ``emulator/``, ``toolchain/``, and
this package's own directory, so the module works both stand-alone
(``import qsyscalls``) and through the ``qos`` package facade.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

# -- import seams (design doc section 8) ------------------------------------
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parents[0] / "emulator"))
sys.path.insert(0, str(_HERE.parents[0] / "toolchain"))
sys.path.insert(0, str(_HERE))
import qcpu  # noqa: E402  (path seam must run first)
import scheduler as _scheduler  # noqa: E402

try:  # builder A's assembler, when present (design doc section 8.1)
    import qas as _qas  # type: ignore[import-not-found]
except ImportError:  # toolchain not built yet; use the qcpu-backed fallback
    _qas = None

# -- constants mirrored from qsyscall.h (names identical; design doc 8.3).
# Canonical values live in scheduler.py to keep the qos dependency graph
# acyclic; this module is their contractual export point.
from scheduler import (  # noqa: E402,F401  (re-exports are the contract)
    QTOPO_ANY, QTOPO_LINE, QTOPO_GRID, QTOPO_ALL2ALL,
    QDEADLINE_RELAXED, QMR_F_PARTIAL,
    QLEASE_STATE_LIVE, QLEASE_STATE_CONSUMED, QLEASE_STATE_STALE,
    QLEASE_MAX_QUBITS,
    QSET_F_CLOFORK, QSET_F_NODUP, QSET_F_NOMMAP,
    QLOSError, PoolExhaustedError, CoherenceBudgetError,
    VerifierRejectError, FidelityFloorError, LeaseStaleError,
    PhysUndefinedError, BadDescriptorError,
    Lease, LeaseManager, QProcess, QProcState, QPUScheduler,
    QObjLike,
)

#: Provisional syscall numbers (qsyscall.h __NR_* block), re-exported for
#: the conformance test. Dunder module attributes are not name-mangled at
#: module level; tests in class bodies should use ``getattr``.
__NR_qalloc: int = _scheduler.__NR_qalloc
__NR_qexec: int = _scheduler.__NR_qexec
__NR_qmeasure: int = _scheduler.__NR_qmeasure
__NR_qfree: int = _scheduler.__NR_qfree

#: First qset fd handed out; 0..2 stay conventionally classical (stdio).
_FIRST_QSET_FD: int = 3


@dataclass(frozen=True)
class _FallbackQObj:
    """Minimal QObj-shaped object built straight from ``qcpu.assemble``.

    Used by :func:`_assemble_source` only while ``toolchain/qas.py`` is
    absent. Carries exactly the fields the runtime and scheduler consume
    (the :class:`scheduler.QObjLike` protocol plus requirements); it does
    NOT carry the full section 6.2 envelope (``stats``, ``source_sha256``)
    -- those are toolchain deliverables, not runtime ones.
    """

    n_qubits: int
    n_shadow: int
    n_gpr: int
    instructions: tuple[qcpu.Instruction, ...]
    labels: dict[str, int]

    def to_program(self) -> qcpu.Program:
        """View as a :class:`qcpu.Program` for ``QCPU.verify``/``run``."""
        return qcpu.Program(instructions=self.instructions,
                            labels=self.labels)


def _assemble_source(text: str, isa: qcpu.ISA | None = None) -> Any:
    """Assemble ``.qs`` text into a QObj-shaped object (the qexec str path).

    Delegates to ``toolchain/qas.assemble`` when importable (design doc
    section 8.3: "qexec accepting str assembles on the fly via
    qas.assemble"); otherwise falls back to ``qcpu.assemble`` plus a
    minimal requirements scan -- semantically identical, because qas is
    contractually required to delegate parsing to ``qcpu.assemble``
    (design doc section 6.1/6.3).

    Args:
        text: QISA-K assembly source.
        isa: Optional pre-loaded ISA table.

    Raises:
        qcpu.QISAVerifierError: -ENOEXEC on malformed source (callers wrap
            this into :class:`VerifierRejectError`).
    """
    if _qas is not None:
        return _qas.assemble(text, isa=isa)
    the_isa = isa if isa is not None else qcpu.ISA()
    program = qcpu.assemble(text, the_isa)
    max_idx = {"qubit": -1, "shadow": -1, "gpr": -1}
    for ins in program.instructions:
        spec = the_isa[ins.opcode]
        for value, op_spec in zip(ins.operands, spec.operands):
            if op_spec.kind in max_idx:
                max_idx[op_spec.kind] = max(max_idx[op_spec.kind], value)
    return _FallbackQObj(
        n_qubits=max_idx["qubit"] + 1,
        n_shadow=max_idx["shadow"] + 1,
        n_gpr=max_idx["gpr"] + 1,
        instructions=program.instructions,
        labels=dict(program.labels),
    )


# ---------------------------------------------------------------------------
# Result structs (mirrors of qsyscall.h structs; classical data only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaseInfo:
    """Mirror of ``struct qlease_desc`` (qsyscall.h QPU_IOC_LEASE_INFO).

    The holder-readable, kernel-side view of a qset fd capability. Every
    field is classical lease METADATA; the quantum state itself has no
    readable view [Proven] (measurement postulate -- research doc,
    Invariant 2).

    Attributes:
        lease_id: Capability serial (``qlease_desc.lease_id``).
        n_qubits: Leased qubit count (virtual ids q0..q[n-1]).
        cal_epoch: Calibration generation at placement time.
        state: ``QLEASE_STATE_LIVE`` / ``_CONSUMED`` / ``_STALE``.
        flags: ``QSET_F_*`` bits; CLOFORK|NODUP|NOMMAP are always set --
            they document unconditionally enforced invariants, not options.
        vq_to_pq: Virtual->physical qubit table ("lease assumed: q0, q1
            mapped by the kernel's virtual->physical qubit table" --
            research doc, Bell-pair listing).
    """

    lease_id: int
    n_qubits: int
    cal_epoch: int
    state: int
    flags: int
    vq_to_pq: tuple[int, ...]


@dataclass(frozen=True)
class MeasureResult:
    """Mirror of ``struct qmeasure_result`` (qsyscall.h).

    The classical shadow readout buffer: the ONLY thing that ever crosses
    the syscall boundary upward. The measurement that produced it was
    destructive and irreversible [Proven] (projective collapse); the
    snapshots here are ordinary copyable ints precisely because they are
    classical.

    Attributes:
        shots: Shots actually returned (``qmeasure_result.shots``); fewer
            than submitted when the ring overflowed (see ``flags``).
        n_qubits: Qubits read out per shot.
        fidelity_est: Estimated readout fidelity, percent. EMULATED as the
            runtime's constant ``readout_fidelity`` -- the backend is a
            noiseless statevector (design doc limitation 1); real
            estimates drift with calibration [Demonstrated].
        flags: ``QMR_F_PARTIAL`` when fewer shots than requested survive
            (ring-buffer overflow).
        snapshots: Per-shot shadow register files, e.g. ``{"c0": 1,
            "c1": 1}`` -- the format of ``qcpu.ClassicalRegisterFile
            .snapshot``.
    """

    shots: int
    n_qubits: int
    fidelity_est: int
    flags: int
    snapshots: tuple[dict[str, int], ...]

    def counts(self) -> dict[str, int]:
        """Histogram of shot bitstrings, keyed ``"c{n-1}...c1c0"``.

        The classical post-processing every quantum workflow ends with
        (research doc, userspace flow: histograms are ordinary files).

        Returns:
            Mapping bitstring -> occurrence count over all shots.
        """
        hist: dict[str, int] = {}
        for snap in self.snapshots:
            key = "".join(str(snap[f"c{i}"])
                          for i in range(self.n_qubits - 1, -1, -1))
            hist[key] = hist.get(key, 0) + 1
        return hist

    def packed_shadow(self) -> bytes:
        """Pack outcomes as ``qmeasure_result.shadow[]`` would arrive.

        Shot-major bit packing, LSB-first per byte: bit
        ``k = shot * n_qubits + qubit`` lands in byte ``k // 8`` at bit
        position ``k % 8``; total length ``(n_qubits * shots + 7) // 8``
        -- matching the research doc's sizing (``uint8_t out[2*4096/8]``
        for 2 qubits x 4096 shots).

        Returns:
            The packed classical shadow payload.
        """
        buf = bytearray((self.n_qubits * self.shots + 7) // 8)
        for shot, snap in enumerate(self.snapshots):
            for q in range(self.n_qubits):
                if snap[f"c{q}"]:
                    k = shot * self.n_qubits + q
                    buf[k // 8] |= 1 << (k % 8)
        return bytes(buf)


# ---------------------------------------------------------------------------
# The runtime
# ---------------------------------------------------------------------------


class QLOSRuntime:
    """User-space realization of the qsyscall.h four-call ABI (section 4).

    Wraps the ``qcpu`` emulator behind ``qalloc``/``qexec``/``qmeasure``/
    ``qfree`` with the exact errno contract of the header, composing one
    root :class:`QProcess` (pid 1) + :class:`LeaseManager` +
    :class:`QPUScheduler`. The root process is set to the transient
    ``RUNNING`` state inside each call (design doc section 3 lifecycle)
    and settled to NEW/READY/BLOCKED_ON_QPU on return.

    Args:
        n_pool_qubits: Physical pool size (1..min(24, 128); emulator cap,
            design doc limitation 7).
        seed: Master RNG seed for reproducible measurement sampling
            (per-job seeds derive deterministically at submit).
        isa: Optional pre-loaded :class:`qcpu.ISA`.
        coherence_budget_cycles: Default lease budget when ``qalloc`` has
            no ``min_t2_us`` hint ([Theoretical] admission policy).
        readout_fidelity: Constant percent reported as ``fidelity_est``;
            exists because the noiseless emulator would otherwise make
            -EIO unreachable (design doc section 8.3 notes). Lower it to
            exercise the :class:`FidelityFloorError` path.
        ring_capacity_shots: Per-lease measurement ring bound; overflow
            drops oldest snapshots and sets ``QMR_F_PARTIAL``.
    """

    def __init__(self, n_pool_qubits: int = 8, *, seed: int | None = None,
                 isa: qcpu.ISA | None = None,
                 coherence_budget_cycles: int = 10_000,
                 readout_fidelity: int = 100,
                 ring_capacity_shots: int = 65_536) -> None:
        if not 0 <= readout_fidelity <= 100:
            raise ValueError(
                f"readout_fidelity must be 0..100, got {readout_fidelity}")
        self.isa: qcpu.ISA = isa if isa is not None else qcpu.ISA()
        self.lease_mgr: LeaseManager = LeaseManager(
            n_pool_qubits,
            default_budget_cycles=coherence_budget_cycles,
            ring_capacity_shots=ring_capacity_shots,
        )
        self.qpu_sched: QPUScheduler = QPUScheduler(
            self.lease_mgr, seed=seed, isa=self.isa)
        self.readout_fidelity: int = readout_fidelity
        self._root: QProcess = QProcess(pid=1, name="qlos-init")
        self._fds: dict[int, Lease] = {}
        self._fd_shots_enqueued: dict[int, int] = {}
        self._fd_max_floor: dict[int, int] = {}
        self._next_fd: int = _FIRST_QSET_FD

    # -- fd plumbing ----------------------------------------------------------

    def _lease(self, qset_fd: int) -> Lease:
        """Resolve a qset fd or fail with -EBADF (ordinary POSIX -- design
        doc section 4: deliberately NOT in the header's quantum table)."""
        lease = self._fds.get(qset_fd)
        if lease is None:
            raise BadDescriptorError(f"unknown qset fd {qset_fd}")
        return lease

    def _settle_root(self) -> None:
        """Leave the transient RUNNING state (design doc section 3)."""
        if self.qpu_sched.pending_jobs() and self._root.leases:
            self._root.state = QProcState.BLOCKED_ON_QPU
        elif self._root.leases:
            self._root.state = QProcState.READY
        else:
            self._root.state = QProcState.NEW

    # -- the four calls ---------------------------------------------------------

    def qalloc(self, n_qubits: int, *, min_t2_us: int = 0,
               topology: int = QTOPO_ANY) -> int:
        """QALLOC: lease ``n_qubits`` qubits; return a qset fd capability.

        Mirrors ``__NR_qalloc`` (463) / ``QPU_IOC_QALLOC`` with ``struct
        qalloc_hints {min_t2_us, topology}`` as keyword arguments
        (research doc, "Syscall additions" table). NEVER blocks -- fails
        fast with -EBUSY under pool exhaustion, because no overcommit can
        exist where no swap exists [Proven] (swap = tomography over copies
        no-cloning forbids; research doc errno table).

        Emulation note: ``min_t2_us`` becomes the lease's [Theoretical]
        coherence-budget admission parameter (``min_t2_us *
        CYCLES_PER_US`` cycles); on real hardware it is a
        calibration-aware placement hint against per-qubit T2 drift
        [Demonstrated] (qsyscall.h ``qalloc_hints`` commentary).

        Args:
            n_qubits: Qubits to lease (>= 1).
            min_t2_us: Minimum acceptable T2 in microseconds (hint).
            topology: ``QTOPO_*`` requirement; all satisfiable here (the
                statevector is effectively all-to-all).

        Returns:
            A new qset fd (>= 3; 0..2 stay conventionally classical).

        Raises:
            PoolExhaustedError: -EBUSY (pool exhausted; no overcommit).
            ValueError: Classical parameter errors.
        """
        self._root.state = QProcState.RUNNING
        try:
            lease = self.lease_mgr.allocate(
                self._root, n_qubits, min_t2_us=min_t2_us,
                topology=topology)
        finally:
            self._settle_root()
        fd = self._next_fd
        self._next_fd += 1
        self._fds[fd] = lease
        self._fd_shots_enqueued[fd] = 0
        self._fd_max_floor[fd] = 0
        return fd

    def qexec(self, qset_fd: int, qobj: QObjLike | str, *, shots: int = 1,
              deadline_us: int = QDEADLINE_RELAXED,
              fidelity_floor: int = 0) -> int:
        """QEXEC: verify, admit, and enqueue a circuit; return its job id.

        Mirrors ``__NR_qexec`` (464) / ``QPU_IOC_QEXEC`` with ``struct
        qexec_submit {qir_blob, len, params}`` and ``struct qexec_params
        {shots, deadline, fidelity_floor, ff_table...}`` as keyword
        arguments. NEVER blocks: static verification and admission run
        synchronously, execution is deferred -- the runtime analogue of
        the header's async submit with io_uring CQE completion. The
        program -- never the quantum state -- is the only thing crossing
        this boundary downward, and it is re-verified here as untrusted
        input exactly as ELF is (design doc section 6.3; the verifier is
        the emulator's own ``QCPU.verify`` over the QISA-v0.1.yaml
        ``verifier_rules``, run against the REAL lease size).

        Feed-forward note: the header's ``ff_table`` is not surfaced;
        QISA-K feed-forward (``FMR``/``BRN``) rides inside the program and
        executes in the emulator's instruction loop -- on hardware it
        lives in control firmware inside the coherence window
        [Demonstrated] (eQASM; QNodeOS; design doc limitation 5).

        Args:
            qset_fd: Capability from :meth:`qalloc`.
            qobj: An assembled QObj (anything satisfying
                ``scheduler.QObjLike``) or QISA-K assembly text, assembled
                on the fly (parity with ``QCPU.run``).
            shots: Statistically independent trials (>= 1).
            deadline_us: ``QDEADLINE_RELAXED`` (0) or a relative soft
                deadline in microseconds (EDF admission hint).
            fidelity_floor: Percent; readout below it fails the eventual
                :meth:`qmeasure` with -EIO.

        Returns:
            The job id (>= 0; information-compatible with the C ABI's 0).

        Raises:
            BadDescriptorError: -EBADF (unknown fd).
            VerifierRejectError: -ENOEXEC (unleased qubit,
                use-after-measure without RESET, malformed program).
            PhysUndefinedError: -EPERM (qexec after qmeasure: reuse of a
                consumed use-at-most-once capability, section 3 rule 3).
            LeaseStaleError: -ESTALE (recalibration; re-qalloc).
            CoherenceBudgetError: -ETIME (per-shot estimate exceeds the
                remaining lease budget or the job's own deadline budget).
        """
        lease = self._lease(qset_fd)
        self._root.state = QProcState.RUNNING
        try:
            if isinstance(qobj, str):
                try:
                    qobj = _assemble_source(qobj, self.isa)
                except qcpu.QISAVerifierError as exc:
                    self.qpu_sched._reject("ENOEXEC", self._root)
                    raise VerifierRejectError(
                        f"malformed program text: {exc}") from exc
            job_id = self.qpu_sched.submit(
                lease, qobj, shots=shots, deadline_us=deadline_us,
                fidelity_floor=fidelity_floor)
        finally:
            self._settle_root()
        self._fd_shots_enqueued[qset_fd] += shots
        self._fd_max_floor[qset_fd] = max(self._fd_max_floor[qset_fd],
                                          fidelity_floor)
        return job_id

    def qmeasure(self, qset_fd: int) -> MeasureResult:
        """QMEASURE: block until the lease's jobs finish, drain its ring.

        Mirrors ``__NR_qmeasure`` (465) / ``QPU_IOC_QMEASURE``, filling
        the Python image of ``struct qmeasure_result {shots, n_qubits,
        fidelity_est, flags, payload_len, shadow[]}`` (``payload_len`` is
        implicit: ``len(packed_shadow())``). BLOCKS until all queued jobs
        on the lease complete -- v0.1 realizes the block by synchronously
        driving ``QPUScheduler.run_pending()`` (design doc section 4) --
        then DESTRUCTIVELY drains the measurement ring buffer.

        Explicitly NOT ``read(2)``-idempotent [Proven]: the readout that
        filled the ring was a projective collapse, so this call consumes
        the lease (LIVE -> CONSUMED); a second ``qmeasure``, like any
        further use of the consumed linear capability, fails with -EPERM
        (design doc section 3 rules 3-4). Only the classical shadow
        crosses the boundary; there is no API returning amplitudes
        (research doc, Invariant 2).

        Args:
            qset_fd: Capability from :meth:`qalloc`.

        Returns:
            The drained :class:`MeasureResult`; ``flags`` carries
            ``QMR_F_PARTIAL`` when the bounded ring dropped early shots.

        Raises:
            BadDescriptorError: -EBADF (unknown fd).
            PhysUndefinedError: -EPERM (second qmeasure on a consumed
                lease).
            LeaseStaleError: -ESTALE (lease staled by recalibration; per
                section 3 rule 4 only ``qfree`` remains valid -- a v0.1
                ABI completion: the header assigns -ESTALE to qexec and
                names no qmeasure-on-stale errno).
            FidelityFloorError: -EIO (readout below the max
                ``fidelity_floor`` of the drained jobs; the call fails
                INSTEAD OF returning data, but the lease is still
                consumed -- the destructive readout happened, it was just
                bad).
        """
        lease = self._lease(qset_fd)
        self._root.state = QProcState.RUNNING
        try:
            if lease.state == QLEASE_STATE_CONSUMED:
                raise PhysUndefinedError(
                    f"qset fd {qset_fd}: second qmeasure on a CONSUMED "
                    "lease -- qmeasure is not read(2)-idempotent [Proven]")
            if lease.state == QLEASE_STATE_STALE:
                raise LeaseStaleError(
                    f"qset fd {qset_fd}: lease staled by recalibration; "
                    "only qfree remains valid (design doc section 3 rule 4)")
            # Block (synchronously) until this lease has no queued jobs.
            while self.qpu_sched.pending_jobs(lease):
                if self.qpu_sched.run_pending() == 0:
                    break  # defensive: nothing executable remains
            snapshots = tuple(lease.ring)
            lease.ring.clear()                    # destructive drain
            lease.state = QLEASE_STATE_CONSUMED   # one-shot capability use
            requested = self._fd_shots_enqueued.get(qset_fd, 0)
            flags = QMR_F_PARTIAL if len(snapshots) < requested else 0
            floor = self._fd_max_floor.get(qset_fd, 0)
            if self.readout_fidelity < floor:
                # Data discarded, lease consumed anyway: the projective
                # collapse already happened (qsyscall.h -EIO semantics).
                raise FidelityFloorError(
                    f"readout fidelity_est={self.readout_fidelity}% below "
                    f"fidelity_floor={floor}% (calibration drift)")
            return MeasureResult(
                shots=len(snapshots),
                n_qubits=lease.n_qubits,
                fidelity_est=self.readout_fidelity,
                flags=flags,
                snapshots=snapshots,
            )
        finally:
            self._settle_root()

    def qfree(self, qset_fd: int) -> int:
        """QFREE: cancel queued jobs, RESET, return qubits, close the fd.

        Mirrors ``__NR_qfree`` (466) / ``QPU_IOC_QFREE``. NEVER blocks and
        never fails for a known fd -- even STALE or CONSUMED leases free
        cleanly, because revocation destroys state rather than copying it,
        which is always physically allowed (RESET is the active |0>
        preparation: measure + conditional X -- qsyscall.h ``qfree``
        commentary). In the emulator the RESET is a no-op since lease
        state never persists between jobs (design doc limitation 3).

        Args:
            qset_fd: Capability from :meth:`qalloc`.

        Returns:
            0, matching the C ABI.

        Raises:
            BadDescriptorError: -EBADF (unknown fd; double-qfree lands
                here, like ``close(2)`` on a closed fd).
        """
        lease = self._lease(qset_fd)
        self._root.state = QProcState.RUNNING
        try:
            self.qpu_sched.cancel_lease(lease)
            self.lease_mgr.release(lease)
            del self._fds[qset_fd]
            self._fd_shots_enqueued.pop(qset_fd, None)
            self._fd_max_floor.pop(qset_fd, None)
        finally:
            self._settle_root()
        return 0

    # -- cross-cutting calls (header "enforced invariants" block) -------------

    def dup(self, qset_fd: int) -> NoReturn:
        """dup() on a qset fd: ALWAYS -EPERM (QERR_PHYS_UNDEFINED).

        Duplicating the capability would duplicate the underlying
        resource, i.e. copy live quantum state -- physically undefined
        [Proven] (no-cloning theorem, Wootters & Zurek 1982; qsyscall.h
        ``QSET_F_NODUP`` commentary; research doc, "Enforced invariants").
        An unknown fd fails -EBADF first, per ordinary POSIX ``dup(2)``.

        Raises:
            BadDescriptorError: -EBADF (unknown fd).
            PhysUndefinedError: -EPERM (always, for any live fd).
        """
        lease = self._lease(qset_fd)
        raise PhysUndefinedError(
            f"dup() of qset fd {qset_fd} (lease {lease.lease_id}): "
            "duplication is copying -- physically undefined [Proven]")

    def lease_info(self, qset_fd: int) -> LeaseInfo:
        """Read the lease descriptor (``QPU_IOC_LEASE_INFO``).

        Returns the classical METADATA view of ``struct qlease_desc`` --
        reading metadata is free precisely because it is classical; the
        quantum state behind it has no non-destructive view [Proven]
        (measurement postulate, research doc Invariant 2).

        Args:
            qset_fd: Capability from :meth:`qalloc`.

        Returns:
            The :class:`LeaseInfo` mirror, ``flags`` always carrying
            CLOFORK|NODUP|NOMMAP (unconditional invariants, not options).

        Raises:
            BadDescriptorError: -EBADF (unknown fd).
        """
        lease = self._lease(qset_fd)
        return LeaseInfo(
            lease_id=lease.lease_id,
            n_qubits=lease.n_qubits,
            cal_epoch=lease.cal_epoch,
            state=lease.state,
            flags=QSET_F_CLOFORK | QSET_F_NODUP | QSET_F_NOMMAP,
            vq_to_pq=lease.vq_to_pq,
        )

    def recalibrate(self) -> int:
        """Trigger a recalibration cycle: new epoch, LIVE leases go STALE.

        The -ESTALE test seam (design doc section 4; workflow Risk 6 --
        drift handling deferred, this stubs the recalibration event). On
        hardware the QCX calibration store backs this epoch
        [Theoretical] (design doc section 9, future work).

        Returns:
            The new calibration epoch.
        """
        return self.lease_mgr.recalibrate()

    def stats(self) -> dict[str, Any]:
        """Global runtime statistics; delegates to ``QPUScheduler.stats``."""
        return self.qpu_sched.stats()


def _demo() -> None:
    """The design doc section 7 worked example: bell.qs -> counts."""
    rt = QLOSRuntime(n_pool_qubits=8, seed=42)
    fd = rt.qalloc(2, min_t2_us=200)
    rt.qexec(fd, qcpu.BELL_UNCORRECTED_ASM, shots=4096, fidelity_floor=95)
    res = rt.qmeasure(fd)
    print(f"lease: {rt.lease_info(fd)}")
    print(f"counts: {res.counts()}  (never '01'/'10')")
    rt.qfree(fd)
    print(f"stats: {rt.stats()}")


if __name__ == "__main__":
    _demo()
