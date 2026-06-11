"""qas -- the QLOS assembler (the ``cc`` of the QuantumLinux toolchain).

Assembles QISA-K ``.qs`` text into the QOBJ v0.1 JSON object format defined
by quantum-linux/qos/QLOS-DESIGN-v0.1.md (sections 6.2 and 8.1, BINDING).
The surface syntax is EXACTLY what ``qcpu.assemble()`` parses -- this module
adds no syntax and delegates all parsing to the emulator's loader (design
doc section 6.1), then layers on:

* **Load-time protection** (design doc section 6.3 -- the MMU analogue:
  reject before any state exists): every instruction is validated against
  quantum-linux/isa-spec/QISA-v0.1.yaml. Unknown opcodes, bad operand
  counts/types, and out-of-range registers are assembly errors carrying
  source line numbers, raised as :class:`qcpu.QISAVerifierError` with
  ``.errno == -ENOEXEC`` -- the research doc's verifier-rejection errno
  (docs/research/02-quantum-linux.md, errno table; "malformed QIR").
* **Static verification**: the emulator's own verifier
  (:meth:`qcpu.QCPU.verify`) runs over a throwaway QCPU sized to the
  program's own qubit requirements, enforcing the QISA-v0.1.yaml
  ``verifier_rules`` (no-use-after-measure-without-RESET, no qubit-operand
  duplication, classical-register range checks). The lease-relative
  ``no-gate-on-unleased-qubit`` rule is necessarily re-checked at ``qexec``
  against the real lease (design doc section 6.3, defense in depth).
* **Static statistics**: assembled gate counts, two-qubit-gate count,
  measure count, QWAIT cycle total, instruction count -- distinct from
  ``QCPU``'s *runtime* counters (design doc section 6.2) -- plus a SHA-256
  hash of the source text.

What is EMULATED vs REAL: everything here is classical tooling -- an
assembler manipulates circuit *descriptions* (ordinary files), never quantum
state, exactly as the research doc's VFS audit prescribes ("files hold
circuit descriptions ... ordinary files"). On real hardware the QOBJ
envelope would wrap a QIR/OpenQASM 3 blob submitted through ``qexec``
(qsyscall.h, ``struct qexec_submit``); the verify-before-execute discipline
is the same **[Demonstrated]** pattern every deployed control plane uses.
The 32-bit binary encodings sketched in QISA-v0.1.yaml are NOT emitted --
v0.1 objects are JSON envelopes ("the 'ELF' of this stack" is a format
contract, not a binary layout claim) **[Theoretical]**.

Runtime dependencies: numpy (transitively, via qcpu) and optionally PyYAML.
When PyYAML is absent, :class:`qcpu.ISA` falls back to its vendored decode
table (kept in sync with QISA-v0.1.yaml), so the toolchain inherits the
emulator's fallback behavior with no extra code path here.

CLI::

    qas.py input.qs -o out.qobj.json   # assemble to a QOBJ JSON file
    qas.py input.qs                    # assemble, print QOBJ JSON to stdout
    qas.py input.qs --verify-only      # validate + verify, emit nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Import seam (design doc section 8, binding): the toolchain drives the
# emulator package by path, keeping quantum-linux/ free of installed-package
# assumptions.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "emulator"))

import qcpu

#: QOBJ envelope identification (design doc section 6.2 / 8.1).
QOBJ_FORMAT: str = "QOBJ"
QOBJ_VERSION: str = "0.1"

#: Required top-level keys of a QOBJ v0.1 envelope (design doc section 6.2).
_ENVELOPE_KEYS: frozenset[str] = frozenset({
    "format", "format_version", "isa", "requirements", "entry",
    "instructions", "labels", "stats", "source_sha256",
})

#: Lazily constructed shared default ISA (loads QISA-v0.1.yaml once).
_DEFAULT_ISA: qcpu.ISA | None = None


def _default_isa() -> qcpu.ISA:
    """Return the module-shared default :class:`qcpu.ISA` (lazy singleton).

    Loaded from QISA-v0.1.yaml when PyYAML is importable; otherwise
    ``qcpu.ISA`` transparently uses its vendored fallback table -- the
    toolchain's "vendored YAML fallback" is the emulator's own.
    """
    global _DEFAULT_ISA
    if _DEFAULT_ISA is None:
        _DEFAULT_ISA = qcpu.ISA()
    return _DEFAULT_ISA


def _operand_kinds(isa: qcpu.ISA, opcode: str) -> tuple[str, ...]:
    """Operand kinds for ``opcode``, positionally, from the ISA spec."""
    return tuple(spec.kind for spec in isa[opcode].operands)


def _requirements(
    instructions: tuple[qcpu.Instruction, ...], isa: qcpu.ISA
) -> tuple[int, int, int]:
    """Compute minimum register-file requirements (design doc section 6.2).

    Returns ``(n_qubits, n_shadow, n_gpr)``, each the highest register index
    used plus one (0 when the kind is unused). These are *minimums*: the
    lease backing ``qexec`` may be larger, never smaller.
    """
    n_qubits = n_shadow = n_gpr = 0
    for ins in instructions:
        for value, kind in zip(ins.operands, _operand_kinds(isa, ins.opcode)):
            if kind == "qubit":
                n_qubits = max(n_qubits, value + 1)
            elif kind == "shadow":
                n_shadow = max(n_shadow, value + 1)
            elif kind == "gpr":
                n_gpr = max(n_gpr, value + 1)
    return n_qubits, n_shadow, n_gpr


def _static_stats(
    instructions: tuple[qcpu.Instruction, ...], isa: qcpu.ISA
) -> dict[str, Any]:
    """Compute the static (assembled) statistics block of section 6.2.

    These are counts over the assembled instruction *stream*, deliberately
    distinct from ``QCPU``'s runtime counters: a BRN-skipped instruction
    still counts here, and shots multiply nothing. Keys are binding:
    ``gate_counts``, ``two_qubit_gate_count``, ``measure_count``,
    ``qwait_cycles``, ``instruction_count``.
    """
    gate_counts: dict[str, int] = {}
    two_q = 0
    measure = 0
    qwait_cycles = 0
    for ins in instructions:
        gate_counts[ins.opcode] = gate_counts.get(ins.opcode, 0) + 1
        kinds = _operand_kinds(isa, ins.opcode)
        if kinds.count("qubit") == 2:
            two_q += 1
        if ins.opcode == "MEASURE":
            measure += 1
        if ins.opcode == "QWAIT":
            qwait_cycles += int(ins.operands[0])
    return {
        "gate_counts": gate_counts,
        "two_qubit_gate_count": two_q,
        "measure_count": measure,
        "qwait_cycles": qwait_cycles,
        "instruction_count": len(instructions),
    }


def _verify_static(
    program: qcpu.Program, n_qubits: int, isa: qcpu.ISA
) -> None:
    """Run the emulator's static verifier over a throwaway QCPU.

    Per design doc section 6.3 the throwaway machine is sized
    ``max(n_qubits, 1)`` -- a lease exactly the program's own size -- so
    the QISA-v0.1.yaml ``verifier_rules`` are enforced at assemble time
    (load-time protection). The emulator-capacity cap ``qcpu.MAX_QUBITS``
    (a dense-statevector limit, NOT the [Proven] tomography bound -- do not
    conflate, design doc section 9 row 7) is translated into an assembly
    error with a line number rather than leaking a ``ValueError``.

    Raises:
        qcpu.QISAVerifierError: With ``errno == -ENOEXEC`` on any violation.
    """
    if n_qubits > qcpu.MAX_QUBITS:
        for ins in program.instructions:
            for value, kind in zip(
                ins.operands, _operand_kinds(isa, ins.opcode)
            ):
                if kind == "qubit" and value >= qcpu.MAX_QUBITS:
                    raise qcpu.QISAVerifierError(
                        f"line {ins.line_no}: qubit register q{value} "
                        f"exceeds the emulator capacity cap "
                        f"(MAX_QUBITS={qcpu.MAX_QUBITS}; this is a dense-"
                        f"statevector limit, not a physical bound)",
                        rule="no-gate-on-unleased-qubit",
                    )
    cpu = qcpu.QCPU(n_qubits=max(n_qubits, 1), isa=isa)
    cpu.verify(program)


def _envelope_error(message: str) -> qcpu.QISAVerifierError:
    """Build the QOBJ-envelope rejection error (rule: malformed-program).

    A QOBJ file is untrusted input exactly as an ELF file is (design doc
    section 6.3); envelope violations map onto the research doc's
    "malformed QIR" -ENOEXEC cause.
    """
    return qcpu.QISAVerifierError(
        f"malformed QOBJ envelope: {message}", rule="malformed-program"
    )


def _decode_operand(
    value: Any, kind: str, line_no: int, opcode: str
) -> Any:
    """Coerce one JSON operand value to its ISA kind, or reject.

    Mirrors the type discipline of ``qcpu.assemble``: register/immediate
    operands are non-negative ints, angles are floats, labels are strings.

    Raises:
        qcpu.QISAVerifierError: On a type/range mismatch.
    """
    if kind in ("qubit", "shadow", "gpr", "imm"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _envelope_error(
                f"instruction at line {line_no} ({opcode}): {kind} operand "
                f"must be an integer, got {value!r}")
        if value < 0:
            raise _envelope_error(
                f"instruction at line {line_no} ({opcode}): negative "
                f"{kind} operand {value}")
        return value
    if kind == "angle":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _envelope_error(
                f"instruction at line {line_no} ({opcode}): angle operand "
                f"must be a number, got {value!r}")
        return float(value)
    if kind == "label":
        if not isinstance(value, str):
            raise _envelope_error(
                f"instruction at line {line_no} ({opcode}): label operand "
                f"must be a string, got {value!r}")
        return value
    raise _envelope_error(  # pragma: no cover -- ISA kinds are closed
        f"unknown operand kind {kind!r}")


@dataclass(frozen=True)
class QObj:
    """An assembled QOBJ v0.1 object (design doc sections 6.2 / 8.1).

    The in-memory form of the JSON envelope -- the "ELF" of this stack:
    instructions plus label map (the executable payload), minimum register
    requirements, static statistics, and a source hash for provenance.
    Purely classical data; only the *program* ever crosses the syscall
    boundary downward (research doc, userspace-flow section).

    Attributes:
        isa_name: ISA identification, ``"QISA-K"``.
        isa_version: ISA version, ``"0.1"``.
        n_qubits: Minimum qubit count (highest ``q`` index used + 1).
        n_shadow: Minimum shadow-register count (highest ``c`` index + 1).
        n_gpr: Minimum GPR count (highest ``r`` index + 1).
        entry: Entry instruction index; always 0 in v0.1.
        instructions: Decoded :class:`qcpu.Instruction` stream, carrying
            ``line_no``/``source`` so diagnostics survive the round trip.
        labels: Label name -> instruction index map.
        stats: Static assembled counts (schema section 6.2).
        source_sha256: Hex SHA-256 of the ``.qs`` source text.
    """

    isa_name: str
    isa_version: str
    n_qubits: int
    n_shadow: int
    n_gpr: int
    entry: int
    instructions: tuple[qcpu.Instruction, ...]
    labels: dict[str, int]
    stats: dict[str, Any]
    source_sha256: str

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize to the QOBJ v0.1 JSON envelope (section 6.2 schema).

        Args:
            indent: ``json.dumps`` indent; ``None`` for compact output.

        Returns:
            The JSON envelope text (no trailing newline).
        """
        envelope: dict[str, Any] = {
            "format": QOBJ_FORMAT,
            "format_version": QOBJ_VERSION,
            "isa": {"name": self.isa_name, "version": self.isa_version},
            "requirements": {
                "n_qubits": self.n_qubits,
                "n_shadow": self.n_shadow,
                "n_gpr": self.n_gpr,
            },
            "entry": self.entry,
            "instructions": [
                {
                    "opcode": ins.opcode,
                    "operands": list(ins.operands),
                    "line_no": ins.line_no,
                    "source": ins.source,
                }
                for ins in self.instructions
            ],
            "labels": dict(self.labels),
            "stats": self.stats,
            "source_sha256": self.source_sha256,
        }
        return json.dumps(envelope, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "QObj":
        """Parse and *fully validate* a QOBJ v0.1 JSON envelope.

        An object file is untrusted input, exactly as ELF is (design doc
        section 6.3): the envelope is structurally checked, every
        instruction is re-validated against the ISA spec (opcode, operand
        count, operand kinds), the ``requirements`` and ``stats`` blocks
        are recomputed and must match, instruction ``line_no`` values must
        be strictly increasing positive ints (the property ``qcpu.assemble``
        guarantees and ``qdis`` relies on for line-faithful round trips),
        and the emulator's static verifier is re-run.

        Raises:
            qcpu.QISAVerifierError: With ``errno == -ENOEXEC`` on any bad
                envelope -- no new exception types exist in the toolchain
                (design doc section 8.1).
        """
        isa = _default_isa()
        try:
            env = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _envelope_error(f"not valid JSON ({exc})") from exc
        if not isinstance(env, dict):
            raise _envelope_error("top level must be a JSON object")
        missing = _ENVELOPE_KEYS - env.keys()
        if missing:
            raise _envelope_error(f"missing key(s): {sorted(missing)}")
        if env["format"] != QOBJ_FORMAT:
            raise _envelope_error(f"format {env['format']!r} != 'QOBJ'")
        if env["format_version"] != QOBJ_VERSION:
            raise _envelope_error(
                f"format_version {env['format_version']!r} != '0.1'")

        isa_block = env["isa"]
        exp_name = str(isa.meta.get("name", "QISA-K"))
        exp_version = str(isa.meta.get("version", "0.1"))
        if (not isinstance(isa_block, dict)
                or isa_block.get("name") != exp_name
                or str(isa_block.get("version")) != exp_version):
            raise _envelope_error(
                f"isa block {isa_block!r} does not name "
                f"{exp_name} v{exp_version}")

        if env["entry"] != 0:
            raise _envelope_error(
                f"entry {env['entry']!r} != 0 (always 0 in v0.1)")

        raw_instructions = env["instructions"]
        if not isinstance(raw_instructions, list):
            raise _envelope_error("instructions must be a JSON array")
        instructions: list[qcpu.Instruction] = []
        prev_line = 0
        for i, raw in enumerate(raw_instructions):
            if not isinstance(raw, dict):
                raise _envelope_error(f"instruction #{i} is not an object")
            for key in ("opcode", "operands", "line_no", "source"):
                if key not in raw:
                    raise _envelope_error(
                        f"instruction #{i} missing {key!r}")
            opcode = raw["opcode"]
            if not isinstance(opcode, str) or opcode not in isa:
                raise _envelope_error(
                    f"instruction #{i}: unknown opcode {opcode!r}")
            line_no = raw["line_no"]
            if (isinstance(line_no, bool) or not isinstance(line_no, int)
                    or line_no <= prev_line):
                raise _envelope_error(
                    f"instruction #{i}: line_no {line_no!r} must be a "
                    f"positive int strictly greater than the previous "
                    f"instruction's ({prev_line})")
            prev_line = line_no
            source = raw["source"]
            if not isinstance(source, str):
                raise _envelope_error(
                    f"instruction #{i}: source must be a string")
            kinds = _operand_kinds(isa, opcode)
            raw_ops = raw["operands"]
            if not isinstance(raw_ops, list) or len(raw_ops) != len(kinds):
                raise _envelope_error(
                    f"instruction #{i} ({opcode}): expected "
                    f"{len(kinds)} operand(s), got {raw_ops!r}")
            operands = tuple(
                _decode_operand(v, k, line_no, opcode)
                for v, k in zip(raw_ops, kinds)
            )
            instructions.append(qcpu.Instruction(
                opcode=opcode, operands=operands,
                line_no=line_no, source=source,
            ))

        labels = env["labels"]
        if not isinstance(labels, dict):
            raise _envelope_error("labels must be a JSON object")
        for name, idx in labels.items():
            if (not isinstance(name, str) or isinstance(idx, bool)
                    or not isinstance(idx, int)
                    or not 0 <= idx <= len(instructions)):
                raise _envelope_error(
                    f"label {name!r} -> {idx!r} out of range "
                    f"0..{len(instructions)}")
        for ins in instructions:
            if ins.opcode == "BRN" and ins.operands[1] not in labels:
                raise _envelope_error(
                    f"BRN at line {ins.line_no} targets undefined label "
                    f"{ins.operands[1]!r}")

        ins_tuple = tuple(instructions)
        n_qubits, n_shadow, n_gpr = _requirements(ins_tuple, isa)
        req = env["requirements"]
        expected_req = {
            "n_qubits": n_qubits, "n_shadow": n_shadow, "n_gpr": n_gpr,
        }
        if req != expected_req:
            raise _envelope_error(
                f"requirements {req!r} do not match the instruction "
                f"stream's minimums {expected_req!r}")
        stats = _static_stats(ins_tuple, isa)
        if env["stats"] != stats:
            raise _envelope_error(
                f"stats {env['stats']!r} do not match the recomputed "
                f"static stats {stats!r}")

        digest = env["source_sha256"]
        if (not isinstance(digest, str) or len(digest) != 64
                or any(ch not in "0123456789abcdefABCDEF" for ch in digest)):
            raise _envelope_error(
                f"source_sha256 {digest!r} is not a hex SHA-256 digest")

        program = qcpu.Program(instructions=ins_tuple,
                               labels=dict(labels))
        _verify_static(program, n_qubits, isa)
        return cls(
            isa_name=exp_name, isa_version=exp_version,
            n_qubits=n_qubits, n_shadow=n_shadow, n_gpr=n_gpr,
            entry=0, instructions=ins_tuple, labels=dict(labels),
            stats=stats, source_sha256=digest,
        )

    def to_program(self) -> qcpu.Program:
        """Repackage as a :class:`qcpu.Program` for ``QCPU.run``/``verify``.

        The instruction tuple is shared (instructions are frozen
        dataclasses -- copying classical data is legal; it is the quantum
        registers that no-cloning [Proven] forbids copying).
        """
        return qcpu.Program(instructions=self.instructions,
                            labels=dict(self.labels))


def assemble(source: str, *, isa: qcpu.ISA | None = None) -> QObj:
    """Assemble ``.qs`` text into a verified :class:`QObj`.

    The load-time protection pipeline (design doc section 6.3):

    1. ``qcpu.assemble(source, isa)`` -- decode-level validation against
       the QISA-v0.1.yaml table: unknown opcode, bad operand count, bad
       operand type, malformed register tokens, undefined BRN targets, and
       duplicate labels are all rejected here with source line numbers.
    2. Minimum requirements are computed (highest register index + 1).
    3. The emulator's static verifier runs on a throwaway
       ``qcpu.QCPU(n_qubits=max(n_qubits, 1))`` -- a lease exactly the
       program's own size -- enforcing the YAML ``verifier_rules``
       (use-after-measure, qubit-operand duplication, classical-register
       ranges). Out-of-range registers therefore reject at assemble time.
    4. Static stats and the source SHA-256 are recorded.

    Args:
        source: QISA-K assembly text (section 6.1 syntax).
        isa: Optional pre-loaded ISA; the shared default otherwise.

    Returns:
        The assembled, verified object.

    Raises:
        qcpu.QISAVerifierError: With ``errno == -ENOEXEC`` and a source
            line number on any validation or verification failure.
    """
    isa_obj = isa if isa is not None else _default_isa()
    program = qcpu.assemble(source, isa_obj)
    n_qubits, n_shadow, n_gpr = _requirements(program.instructions, isa_obj)
    _verify_static(program, n_qubits, isa_obj)
    return QObj(
        isa_name=str(isa_obj.meta.get("name", "QISA-K")),
        isa_version=str(isa_obj.meta.get("version", "0.1")),
        n_qubits=n_qubits, n_shadow=n_shadow, n_gpr=n_gpr,
        entry=0,
        instructions=program.instructions,
        labels=dict(program.labels),
        stats=_static_stats(program.instructions, isa_obj),
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )


def assemble_file(path: str | Path, *, isa: qcpu.ISA | None = None) -> QObj:
    """Assemble a ``.qs`` file (UTF-8) into a verified :class:`QObj`.

    Args:
        path: Path to the assembly source file.
        isa: Optional pre-loaded ISA; the shared default otherwise.

    Raises:
        qcpu.QISAVerifierError: On any validation/verification failure.
        OSError: If the file cannot be read.
    """
    return assemble(Path(path).read_text(encoding="utf-8"), isa=isa)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``qas.py SRC.qs [-o OUT.qobj.json] [--verify-only]``.

    Without ``-o`` the QOBJ JSON is printed to stdout (cc-style filter
    usage); with ``--verify-only`` nothing is emitted -- the exit status is
    the verdict, mirroring ``gcc -fsyntax-only``.

    Returns:
        0 on success; 1 on assembly/verification or I/O failure.
    """
    parser = argparse.ArgumentParser(
        prog="qas.py",
        description="QLOS assembler: QISA-K .qs text -> QOBJ v0.1 JSON, "
                    "validated against QISA-v0.1.yaml at assemble time "
                    "(load-time protection).",
    )
    parser.add_argument("source", help="input .qs assembly file")
    parser.add_argument("-o", "--output", default=None, metavar="OUT",
                        help="output .qobj.json path (default: stdout)")
    parser.add_argument("--verify-only", action="store_true",
                        help="validate and verify only; emit no object")
    args = parser.parse_args(argv)

    try:
        qobj = assemble_file(args.source)
    except qcpu.QISAVerifierError as exc:
        print(f"qas: {args.source}: {exc} [errno {exc.errno}]",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"qas: {args.source}: {exc}", file=sys.stderr)
        return 1

    if args.verify_only:
        print(f"qas: {args.source}: OK -- "
              f"{qobj.stats['instruction_count']} instruction(s), "
              f"requirements q={qobj.n_qubits} c={qobj.n_shadow} "
              f"r={qobj.n_gpr}")
        return 0

    text = qobj.to_json()
    if args.output is not None:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
