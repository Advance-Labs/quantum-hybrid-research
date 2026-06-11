#!/usr/bin/env python3
"""Generate oracle.json — cross-language fixtures for engine.test.ts.

Runs the EXPLAINER-DESIGN.md §4 circuit list on the repository's QISA-K
emulator (quantum-linux/emulator/qcpu.py) — the "Python emulator as
oracle" of docs/research/04-quantum-viz-education.md §4 — and dumps the
exact final statevector of each circuit as [re, im] pairs. The TS engine
(lib/quantum/engine.ts) applies identical matrices in identical order
under the same little-endian qubit convention, so amplitudes must match
to 1e-9 with NO global-phase normalization.

Run with:  /tmp/qhr-venv/bin/python generate_fixtures.py
(numpy + pyyaml; qcpu.py resolves its ISA YAML relative to its own
__file__, so a sys.path insertion is all the path handling needed.)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# site/lib/quantum/fixtures -> parents[3] = repository root.
REPO_ROOT = HERE.parents[3]
EMULATOR_DIR = REPO_ROOT / "quantum-linux" / "emulator"
sys.path.insert(0, str(EMULATOR_DIR))

from qcpu import QCPU  # noqa: E402  (path inserted above)

#: The contract circuit list (EXPLAINER-DESIGN.md §4). Op token grammar
#: shared with engine.test.ts: "<G><q>" single-qubit (G in H X Y Z S T),
#: "CNOT<control><target>" / "CZ<a><b>" two-qubit.
CIRCUITS: list[tuple[str, int, list[str]]] = [
    ("X0", 1, ["X0"]),
    ("H0", 1, ["H0"]),
    ("H0,S0", 1, ["H0", "S0"]),
    ("H0,S0,S0", 1, ["H0", "S0", "S0"]),
    ("H0,Z0,H0 (interference -> |1>)", 1, ["H0", "Z0", "H0"]),
    ("H0,H0 (identity)", 1, ["H0", "H0"]),
    ("H0,CNOT01 (Bell)", 2, ["H0", "CNOT01"]),
    ("X0,CNOT01", 2, ["X0", "CNOT01"]),
    ("H0,H1", 2, ["H0", "H1"]),
    ("H0,T0", 1, ["H0", "T0"]),
    ("GHZ: H0,CNOT01,CNOT02", 3, ["H0", "CNOT01", "CNOT02"]),
]

_1Q = re.compile(r"^(H|X|Y|Z|S|T)(\d)$")
_2Q = re.compile(r"^(CNOT|CZ)(\d)(\d)$")


def op_to_asm(token: str) -> str:
    """Translate one op token into a QISA-K assembly line."""
    m = _1Q.match(token)
    if m:
        return f"{m.group(1)} q{m.group(2)}"
    m = _2Q.match(token)
    if m:
        return f"{m.group(1)} q{m.group(2)}, q{m.group(3)}"
    raise ValueError(f"unknown op token: {token!r}")


def main() -> None:
    fixtures: list[dict[str, object]] = []
    for name, n_qubits, ops in CIRCUITS:
        cpu = QCPU(n_qubits=n_qubits)
        asm = "\n".join(op_to_asm(t) for t in ops)
        cpu.run(asm)  # assemble -> verify -> execute (the real path)
        amps = cpu._debug_statevector()  # test-only accessor, by design
        fixtures.append({
            "name": name,
            "nQubits": n_qubits,
            "ops": ops,
            "amps": [[float(a.real), float(a.imag)] for a in amps],
        })
        print(f"  {name:<35} {len(amps)} amps "
              f"(ISA from {'YAML' if cpu.isa.loaded_from_yaml else 'fallback'})")

    out = HERE / "oracle.json"
    out.write_text(json.dumps(fixtures, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(fixtures)} circuits)")


if __name__ == "__main__":
    main()
