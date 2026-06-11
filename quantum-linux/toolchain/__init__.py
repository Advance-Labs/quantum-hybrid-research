"""QLOS toolchain package -- assembler (qas) + disassembler (qdis).

The ``cc``/``objdump`` analogue of the QuantumLinux stack (design doc
quantum-linux/qos/QLOS-DESIGN-v0.1.md, sections 6 and 8.1-8.2): purely
classical tooling that turns ``.qs`` QISA-K assembly into QOBJ v0.1 JSON
objects and back. Nothing here touches quantum state -- circuit
descriptions are ordinary files (research doc
docs/research/02-quantum-linux.md, VFS audit).

Import seam: the package re-exports the flat modules ``qas`` and ``qdis``
(loaded by path, matching the binding seam of design doc section 8) so
``import toolchain`` and a direct ``import qas`` resolve to the SAME module
objects -- one ``QObj`` identity everywhere.

Public API (binding, design doc sections 8.1-8.2):

* :data:`QOBJ_FORMAT`, :data:`QOBJ_VERSION`
* :class:`QObj` -- the assembled object (``to_json`` / ``from_json`` /
  ``to_program``)
* :func:`assemble`, :func:`assemble_file` -- ``.qs`` text/file -> ``QObj``
* :func:`disassemble`, :func:`disassemble_file` -- ``QObj``/file ->
  canonical ``.qs`` text (round-trip law, design doc section 6.3)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qas
import qdis
from qas import QOBJ_FORMAT, QOBJ_VERSION, QObj, assemble, assemble_file
from qdis import disassemble, disassemble_file

__all__ = [
    "QOBJ_FORMAT",
    "QOBJ_VERSION",
    "QObj",
    "assemble",
    "assemble_file",
    "disassemble",
    "disassemble_file",
    "qas",
    "qdis",
]
