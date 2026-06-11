"""qdis -- the QLOS disassembler (the ``objdump`` of the QuantumLinux stack).

Turns a QOBJ v0.1 object (quantum-linux/qos/QLOS-DESIGN-v0.1.md, section
6.2) back into canonical ``.qs`` assembly text, honoring the BINDING
round-trip law of design doc section 6.3::

    assemble(disassemble(q))  yields identical  instructions, labels,
    requirements, and stats   (only source_sha256 may differ)

How the round trip is made exact: every :class:`qcpu.Instruction` in a QOBJ
carries its original ``line_no`` and comment-stripped ``source`` text
(design doc section 6.2: "diagnostics survive the round trip"). The
disassembler therefore re-emits each instruction's ``source`` verbatim *on
its original line number*, padding with blank lines (which the assembler
ignores), and prefixes labels onto the line of the instruction they index
(``qcpu.assemble`` records a label at the next instruction index, so a
same-line prefix reconstructs the identical label map; labels indexing past
the last instruction are emitted on their own trailing lines). Because
``qcpu.assemble`` guarantees strictly increasing line numbers -- and
``QObj.from_json`` re-validates that property on untrusted envelopes --
this placement is always possible.

What is EMULATED vs REAL: disassembly is classical text processing over a
circuit *description* -- it reads no quantum state and could not: a QOBJ is
one of the research doc's "ordinary files" (VFS audit: files hold circuit
descriptions and classical results). Recovering a *program* from an object
is always legal; recovering a *state* from a device is tomography at
Theta(4**n / eps**2) destructive shots [Proven] (research doc, Invariants
1-2) -- the two must not be conflated.

CLI::

    qdis.py file.qobj.json             # print canonical .qs to stdout
    qdis.py file.qobj.json -o out.qs   # write canonical .qs to a file
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import seam (design doc section 8, binding): flat sibling import so qas/
# qdis/tests all share one module identity regardless of entry point.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "emulator"))

import qcpu  # noqa: F401  (re-exported error type; keeps seam explicit)
from qas import QObj


def disassemble(qobj: QObj) -> str:
    """Render a :class:`qas.QObj` as canonical ``.qs`` text.

    The output reassembles -- via :func:`qas.assemble` -- to an object with
    identical ``instructions`` (including ``line_no`` and ``source``),
    ``labels``, requirements, and ``stats`` (round-trip law, design doc
    section 6.3). Only ``source_sha256`` may differ, since the canonical
    text need not be byte-identical to the original source (comments and
    label-only lines are not preserved; line *numbers* are).

    Args:
        qobj: The object to disassemble. Instruction ``line_no`` values
            must be strictly increasing positive ints -- guaranteed for
            objects produced by :func:`qas.assemble` /
            :meth:`qas.QObj.from_json`.

    Returns:
        Canonical assembly text (trailing newline; empty string for an
        empty program with no labels).
    """
    index_to_labels: dict[int, list[str]] = {}
    for name, idx in qobj.labels.items():
        index_to_labels.setdefault(idx, []).append(name)

    lines: list[str] = []
    for i, ins in enumerate(qobj.instructions):
        while len(lines) < ins.line_no - 1:
            lines.append("")  # blank padding; assembler ignores blank lines
        prefix = "".join(f"{name}: "
                         for name in index_to_labels.get(i, ()))
        lines.append(prefix + ins.source)
    # Labels indexing one past the last instruction (e.g. a trailing
    # branch target) re-emit on their own lines.
    for name in index_to_labels.get(len(qobj.instructions), ()):
        lines.append(f"{name}:")
    return "\n".join(lines) + "\n" if lines else ""


def disassemble_file(path: str | Path) -> str:
    """Load a ``.qobj.json`` file and return its canonical ``.qs`` text.

    The envelope is fully validated by :meth:`qas.QObj.from_json` first --
    an object file is untrusted input, exactly as ELF is (design doc
    section 6.3).

    Args:
        path: Path to the QOBJ v0.1 JSON file.

    Raises:
        qcpu.QISAVerifierError: With ``errno == -ENOEXEC`` on a bad
            envelope.
        OSError: If the file cannot be read.
    """
    return disassemble(QObj.from_json(
        Path(path).read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``qdis.py IN.qobj.json [-o OUT.qs]``.

    Without ``-o`` the canonical assembly is printed to stdout
    (objdump-style listing usage).

    Returns:
        0 on success; 1 on a bad envelope or I/O failure.
    """
    parser = argparse.ArgumentParser(
        prog="qdis.py",
        description="QLOS disassembler: QOBJ v0.1 JSON -> canonical .qs "
                    "text (round-trip safe per QLOS-DESIGN-v0.1.md "
                    "section 6.3).",
    )
    parser.add_argument("qobj", help="input .qobj.json object file")
    parser.add_argument("-o", "--output", default=None, metavar="OUT",
                        help="output .qs path (default: stdout)")
    args = parser.parse_args(argv)

    try:
        text = disassemble_file(args.qobj)
    except qcpu.QISAVerifierError as exc:
        print(f"qdis: {args.qobj}: {exc} [errno {exc.errno}]",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"qdis: {args.qobj}: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
