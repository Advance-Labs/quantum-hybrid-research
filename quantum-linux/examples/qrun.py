"""qrun -- the QLOS dev-loop driver (the ``exec`` analogue of this stack).

Closes the normalized developer workflow of the design doc
(quantum-linux/qos/QLOS-DESIGN-v0.1.md, section 7): ``edit`` a ``.qs`` file,
``assemble`` it through the toolchain (``qas`` -- the ``cc`` analogue), then
*run* it here -- one command that leases qubits, submits the verified
program, blocks for the measurement shadow, and prints counts plus gate
statistics, exactly as ``exec`` + stdout would for a classical program::

    qrun.py prog.qs [--shots N] [--seed S] [--trace]

Pipeline (all real public APIs of this repo; nothing reimplemented):

1. ``qas.assemble_file`` -- load-time protection: the program is validated
   against QISA-v0.1.yaml and statically verified at assemble time (design
   doc section 6.3, the MMU analogue).
2. ``qsyscalls.QLOSRuntime`` -- composes the root :class:`scheduler.QProcess`
   (pid 1, the process this program runs as; design doc section 8.3) with a
   :class:`scheduler.LeaseManager` and :class:`scheduler.QPUScheduler`, then
   drives the four-call ABI of ``kernel-patches/qsyscall.h``:
   ``qalloc`` (lease exactly the program's required qubits) -> ``qexec``
   (re-verify as untrusted input, admit under the coherence budget, enqueue
   N seeded shots) -> ``qmeasure`` (block, destructively drain the
   measurement ring) -> ``qfree`` (RESET + return to pool).
3. Print the classical shadow: a counts histogram (key ``c{n-1}...c1c0``)
   and the scheduler's aggregated gate statistics.

What is EMULATED vs what real hardware would do
-----------------------------------------------
The device behind the runtime is the ``emulator/qcpu.py`` dense statevector
(<= 24 qubits -- an emulator-capacity limit, NOT the [Proven]
Theta(4**n/eps**2) tomography bound; design doc limitation 7). Only the
classical shadow ever crosses a boundary upward (research doc
docs/research/02-quantum-linux.md, userspace-flow section): counts and
stats here are exactly the artifacts a real control plane would return.

``--trace`` is the debugger (``gdb``) analogue and is EMULATION-ONLY: it
single-steps ONE debug shot on a private QCPU and prints the statevector
amplitudes after every instruction via ``QCPU._debug_statevector()``. No
physical machine offers this view: non-destructive reads are excluded by
the measurement postulate [Proven] and copies by no-cloning [Proven]
(research doc, Invariants 1-2); on hardware "inspecting the state" becomes
state tomography at Theta(4**n/eps**2) destructive shots over
re-preparations [Proven]. The traced shot consumes its own RNG stream --
it is a separate trajectory from the N shots executed through the runtime.

Runtime dependencies: numpy (transitively via qcpu) and optionally PyYAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import seams (design doc section 8): drive the sibling packages by path so
# qrun works from any cwd with no installed-package assumptions. The qos/
# modules are plain modules behind the same seam, so module identities are
# shared with `import qos` users (qos/__init__.py docstring).
_QL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_QL_ROOT / "emulator"))
sys.path.insert(0, str(_QL_ROOT / "toolchain"))
sys.path.insert(0, str(_QL_ROOT / "qos"))

import qcpu  # noqa: E402  (path seam must run first)
import qas  # noqa: E402
from qsyscalls import QLOSError, QLOSRuntime, QMR_F_PARTIAL  # noqa: E402
from scheduler import estimate_cycles  # noqa: E402

#: Probability floor below which an amplitude is not printed in --trace.
_TRACE_EPS: float = 1e-12

#: Cap on amplitude lines printed per trace step (large registers would
#: otherwise flood the terminal; 2**n amplitudes exist at n qubits).
_TRACE_MAX_AMPLITUDES: int = 32

#: Hard step bound for the tracer, so a pathological BRN loop cannot hang
#: the debugger analogue.
_TRACE_MAX_STEPS: int = 100_000


def _print_amplitudes(cpu: qcpu.QCPU) -> None:
    """Print the nonzero statevector amplitudes of ``cpu`` (trace mode).

    EMULATION-ONLY: backed by ``QCPU._debug_statevector()``, the test/debug
    accessor whose underscore name marks its unphysicality (measurement
    postulate / no-cloning, both [Proven] -- research doc Invariants 1-2).
    Basis labels read ``|q{n-1} ... q1 q0>``, matching the little-endian
    qubit convention of qcpu and the ``counts()`` key order.
    """
    psi = cpu._debug_statevector()
    n = cpu.n_qubits
    shown = 0
    skipped = 0
    for idx, amp in enumerate(psi):
        p = float(abs(amp) ** 2)
        if p <= _TRACE_EPS:
            continue
        if shown < _TRACE_MAX_AMPLITUDES:
            ket = format(idx, f"0{n}b")
            print(f"        |{ket}>  {amp.real:+.6f}{amp.imag:+.6f}j"
                  f"   (p={p:.6f})")
            shown += 1
        else:
            skipped += 1
    if skipped:
        print(f"        ... ({skipped} more nonzero amplitude(s) suppressed)")


def trace_shot(qobj: qas.QObj, *, seed: int | None = None) -> dict[str, int]:
    """Single-step ONE debug shot of ``qobj``, printing state after each step.

    The ``gdb`` analogue of the normalized dev loop (design doc section 7,
    "debug" row). Drives the emulator's own dispatch (``QCPU._execute``,
    which follows BRN feed-forward exactly as ``QCPU.run`` does) on a
    private, lease-sized QCPU after running the static verifier -- nothing
    here touches the QLOS runtime or anything kernel-visible.

    EMULATION-ONLY (honesty contract): amplitude inspection has no physical
    realization -- see the module docstring. The printed trajectory is one
    random shot; measurement steps collapse it irreversibly [Proven].

    Args:
        qobj: The assembled program to trace.
        seed: RNG seed for the debug shot's measurement sampling.

    Returns:
        The shadow-register snapshot after the traced shot.

    Raises:
        qcpu.QISAVerifierError: If the program fails static verification.
        RuntimeError: If the shot exceeds the tracer's step bound.
    """
    n = max(qobj.n_qubits, 1)
    cpu = qcpu.QCPU(n_qubits=n, seed=seed)
    program = qobj.to_program()
    cpu.verify(program)
    print(f"qrun: trace: ONE debug shot on a {n}-qubit emulated QCPU "
          f"(seed={seed})")
    print("qrun: trace: EMULATION-ONLY -- amplitude inspection is "
          "physically impossible on hardware (measurement postulate / "
          "no-cloning, both [Proven]; research doc Invariants 1-2)")
    print("  [  0] initial state |" + "0" * n + ">")
    _print_amplitudes(cpu)
    pc = 0
    steps = 0
    while 0 <= pc < len(program.instructions):
        if steps >= _TRACE_MAX_STEPS:
            raise RuntimeError(
                f"trace aborted after {steps} steps (BRN loop?)")
        ins = program.instructions[pc]
        pc = cpu._execute(ins, program, pc)
        steps += 1
        print(f"  [{steps:3d}] line {ins.line_no:3d}: {ins.source}")
        _print_amplitudes(cpu)
        if ins.opcode in ("MEASURE", "FMR"):
            print(f"        creg: c={cpu.creg.c} r={cpu.creg.r}")
    snapshot = cpu.creg.snapshot()
    print(f"qrun: trace: shadow registers after the shot: {snapshot}")
    return snapshot


def run_file(source: str | Path, *, shots: int = 1024,
             seed: int | None = None, trace: bool = False) -> "object":
    """Assemble ``source`` and run it through the QLOS four-call ABI.

    The ``exec`` analogue: one program, one quantum process (the runtime's
    root :class:`scheduler.QProcess`, pid 1 -- design doc section 8.3), one
    lease sized exactly to the program's requirements, ``shots`` seeded
    statistically independent trials (NOT cooperating threads -- research
    doc, mapping table), and a printed classical shadow.

    Args:
        source: Path to the ``.qs`` assembly file.
        shots: Number of shots to submit (>= 1).
        seed: Master RNG seed (per-job seeds derive deterministically at
            submit -- ``QPUScheduler`` determinism contract).
        trace: Also single-step one EMULATION-ONLY debug shot first.

    Returns:
        The drained :class:`qsyscalls.MeasureResult`.

    Raises:
        qcpu.QISAVerifierError: Assembly/verification failure (-ENOEXEC).
        QLOSError: Any qsyscall.h errno failure from the runtime.
        OSError: If the source file cannot be read.
    """
    qobj = qas.assemble_file(source)
    print(f"qrun: {source}: assembled "
          f"{qobj.stats['instruction_count']} instruction(s), requirements "
          f"q={qobj.n_qubits} c={qobj.n_shadow} r={qobj.n_gpr}, "
          f"est {estimate_cycles(qobj)} cycles/shot "
          f"(sha256 {qobj.source_sha256[:12]}...)")

    if trace:
        trace_shot(qobj, seed=seed)

    n_qubits = max(qobj.n_qubits, 1)
    rt = QLOSRuntime(n_pool_qubits=n_qubits, seed=seed)
    fd = rt.qalloc(n_qubits)
    info = rt.lease_info(fd)
    print(f"qrun: qalloc   -> qset fd {fd} (lease {info.lease_id}, "
          f"pid 1 'qlos-init', vq->pq {info.vq_to_pq})")
    job_id = rt.qexec(fd, qobj, shots=shots)
    print(f"qrun: qexec    -> job {job_id} admitted ({shots} seeded "
          f"shot(s), seed={seed})")
    result = rt.qmeasure(fd)
    partial = " [QMR_F_PARTIAL]" if result.flags & QMR_F_PARTIAL else ""
    print(f"qrun: qmeasure -> {result.shots} shot(s), fidelity_est "
          f"{result.fidelity_est}%{partial}")
    rt.qfree(fd)
    print("qrun: qfree    -> 0 (RESET + returned to pool)")

    counts = result.counts()
    print(f"qrun: counts (key = c{{{n_qubits - 1}..0}}, "
          f"{result.shots} shot(s)):")
    for key in sorted(counts):
        frac = counts[key] / result.shots
        print(f"  {key}  {counts[key]:6d}  ({frac:6.1%})")

    stats = rt.stats()
    gates = " ".join(f"{op}={cnt}"
                     for op, cnt in sorted(stats["gate_counts"].items()))
    print(f"qrun: gate stats: {gates}")
    print(f"qrun: two_qubit_gate_count={stats['two_qubit_gate_count']} "
          f"measure_count={stats['measure_count']} "
          f"shot_count={stats['shot_count']} "
          f"virtual_now_cycles={stats['virtual_now_cycles']}")
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``qrun.py prog.qs [--shots N] [--seed S] [--trace]``.

    Returns:
        0 on success; 1 on assembly/verification, runtime (qsyscall.h
        errno), or I/O failure -- the verdict-as-exit-status convention the
        rest of the toolchain uses.
    """
    parser = argparse.ArgumentParser(
        prog="qrun.py",
        description="QLOS dev-loop driver: assemble a .qs program (qas), "
                    "run it through the QLOS runtime (qalloc/qexec/"
                    "qmeasure/qfree), print measured counts + gate stats. "
                    "--trace single-steps one EMULATION-ONLY debug shot "
                    "with statevector amplitudes (the gdb analogue).",
    )
    parser.add_argument("source", help="input .qs assembly file")
    parser.add_argument("--shots", type=int, default=1024, metavar="N",
                        help="seeded shots to submit (default: 1024)")
    parser.add_argument("--seed", type=int, default=None, metavar="S",
                        help="master RNG seed (default: fresh entropy)")
    parser.add_argument("--trace", action="store_true",
                        help="single-step one debug shot, printing "
                             "per-instruction statevector amplitudes "
                             "(emulation-only; physically impossible on "
                             "hardware)")
    args = parser.parse_args(argv)

    if args.shots < 1:
        print(f"qrun: {args.source}: shots must be >= 1, got {args.shots}",
              file=sys.stderr)
        return 1
    try:
        run_file(args.source, shots=args.shots, seed=args.seed,
                 trace=args.trace)
    except qcpu.QISAVerifierError as exc:
        print(f"qrun: {args.source}: {exc} [errno {exc.errno}]",
              file=sys.stderr)
        return 1
    except QLOSError as exc:
        print(f"qrun: {args.source}: {exc.strerror} "
              f"[qlos_errno {exc.qlos_errno}]", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"qrun: {args.source}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
