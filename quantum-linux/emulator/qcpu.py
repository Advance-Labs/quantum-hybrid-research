"""QISA-K quantum CPU emulator -- NumPy statevector reference backend.

This module implements the Stage 2 emulator of the Linux-on-Quantum workflow
(docs/workflows/02-linux-workflow.md). The instruction set it executes is
QISA-K v0.1, transcribed verbatim from the research doc's QISA table (see
docs/research/02-quantum-linux.md, "Quantum ISA Design" section); the
machine-readable spec lives at quantum-linux/isa-spec/QISA-v0.1.yaml.

What is SIMULATED vs REAL
-------------------------
Everything here is a classical dense-statevector simulation: 2**n complex128
amplitudes (16 * 2**n bytes), realistic to ~24 qubits on a laptop. This is an
*emulator-capacity* limit, distinct from the [Proven] Theta(4**n / eps**2)
tomography cost that forbids serializing unknown quantum state -- do not
conflate the two (workflow, Prerequisites note). The QWAIT cycle counter is
NOT a coherence/timing model; real feed-forward must beat microsecond-to-
millisecond coherence windows and lives in control firmware below any OS code
path [Demonstrated] (eQASM; QNodeOS) -- see the research doc's Bell-listing
commentary and driver-boundary section.

Honesty contract (workflow Stage 2 acceptance criteria)
-------------------------------------------------------
The emulator exposes no API for reading amplitudes from "kernel-visible"
paths: classical results flow only through MEASURE -> shadow register -> FMR,
mirroring the research doc's rule that only the classical shadow crosses any
boundary. A ``_debug_statevector()`` accessor exists for tests, named to make
its unphysicality obvious (no physical machine offers it -- the measurement
postulate [Proven] forbids non-destructive reads).

Conventions
-----------
* Qubit ordering is LITTLE-ENDIAN: qubit ``q`` is bit ``q`` of the basis-state
  index, so ``q0`` is the least-significant bit. Basis state
  ``|q_{n-1} ... q1 q0>`` lives at index ``sum_i q_i * 2**i``. Classical
  registers are likewise little-endian, matching ``meta.classical_endianness``
  in QISA-v0.1.yaml.
* The classical register file (shadow ``c*`` + GPR ``r*``) is the only
  context-switchable machine state (research doc, register model).

Runtime dependencies: NumPy only. PyYAML is used to load the ISA spec when
available; a vendored minimal fallback decode table (kept in sync with
QISA-v0.1.yaml) is used otherwise.
"""

from __future__ import annotations

import errno
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# --------------------------------------------------------------------------
# ISA specification loading
# --------------------------------------------------------------------------

#: Default on-disk location of the machine-readable ISA spec, relative to
#: this file (quantum-linux/emulator/ -> quantum-linux/isa-spec/).
DEFAULT_ISA_PATH: Path = (
    Path(__file__).resolve().parent.parent / "isa-spec" / "QISA-v0.1.yaml"
)

#: Errno value of -ENOEXEC (verifier rejection; research doc errno table:
#: "Verifier rejection: unleased qubit, use-after-measure, or malformed
#: QIR"). Sourced from the stdlib so it stays correct on any platform.
ENOEXEC: int = errno.ENOEXEC

#: Vendored minimal fallback decode table, used only when PyYAML is absent.
#: MUST be kept in sync with quantum-linux/isa-spec/QISA-v0.1.yaml. Each
#: entry: opcode -> (operand kinds tuple, unitary flag). ``unitary`` is
#: True/False for quantum ops and None for purely classical ones ("n/a" in
#: the research doc's table).
_FALLBACK_TABLE: dict[str, tuple[tuple[str, ...], bool | None]] = {
    "H": (("qubit",), True),
    "X": (("qubit",), True),
    "Y": (("qubit",), True),
    "Z": (("qubit",), True),
    "S": (("qubit",), True),
    "T": (("qubit",), True),
    "RX": (("qubit", "angle"), True),
    "RY": (("qubit", "angle"), True),
    "RZ": (("qubit", "angle"), True),
    "CNOT": (("qubit", "qubit"), True),
    "CZ": (("qubit", "qubit"), True),
    "MEASURE": (("qubit", "shadow"), False),
    "RESET": (("qubit",), False),
    "FMR": (("shadow", "gpr"), None),
    "QWAIT": (("imm",), None),
    "BRN": (("gpr", "label"), None),
}


class QISAVerifierError(Exception):
    """Static verifier rejection -- the -ENOEXEC path of the research doc.

    Raised before any instruction executes, when a program violates one of
    the ``verifier_rules`` in QISA-v0.1.yaml (no-gate-on-unleased-qubit,
    no-use-after-measure-without-RESET, no-qubit-operand-duplication-in-
    copy-position, malformed-program) or fails to decode at all (the
    emulator-level analogue of "malformed QIR").

    Attributes:
        errno: Always ``-ENOEXEC`` (-8), matching the research doc's errno
            table row for verifier rejection of a ``qexec`` blob.
        rule: Identifier of the violated verifier rule, when applicable.
    """

    def __init__(self, message: str, rule: str | None = None) -> None:
        super().__init__(message)
        self.errno: int = -ENOEXEC
        self.rule: str | None = rule


@dataclass(frozen=True)
class OperandSpec:
    """One operand slot of an instruction (name + kind).

    Kinds: ``qubit`` (q*), ``shadow`` (c*), ``gpr`` (r*), ``angle`` (float),
    ``imm`` (non-negative int), ``label`` (branch target).
    """

    name: str
    kind: str


@dataclass(frozen=True)
class InstructionSpec:
    """Decoded ISA entry for one opcode, sourced from QISA-v0.1.yaml."""

    opcode: str
    operands: tuple[OperandSpec, ...]
    unitary: bool | None
    semantics: str
    encoding: str


class ISA:
    """Loads and validates the QISA-K instruction table.

    Prefers the machine-readable YAML spec (QISA-v0.1.yaml); falls back to
    the vendored ``_FALLBACK_TABLE`` when PyYAML is not importable, so the
    emulator stays NumPy-only at runtime.

    Args:
        spec_path: Path to QISA-v0.1.yaml; defaults to the in-repo location.
    """

    def __init__(self, spec_path: Path | str = DEFAULT_ISA_PATH) -> None:
        self.spec_path: Path = Path(spec_path)
        self.meta: dict[str, Any] = {}
        self.verifier_rules: dict[str, Any] = {}
        self.instructions: dict[str, InstructionSpec] = {}
        self.loaded_from_yaml: bool = False
        try:
            import yaml  # deferred: PyYAML may be absent at runtime

            with open(self.spec_path, "r", encoding="utf-8") as fh:
                spec = yaml.safe_load(fh)
            self._load_from_spec(spec)
            self.loaded_from_yaml = True
        except ImportError:
            self._load_fallback()

    def _load_from_spec(self, spec: dict[str, Any]) -> None:
        """Populate the instruction table from a parsed YAML spec dict."""
        self.meta = spec["meta"]
        self.verifier_rules = spec["verifier_rules"]
        if self.meta.get("name") != "QISA-K":
            raise ValueError(f"unexpected ISA name: {self.meta.get('name')!r}")
        for entry in spec["instructions"]:
            ops = tuple(
                OperandSpec(name=o["name"], kind=o["kind"])
                for o in entry["operands"]
            )
            self.instructions[entry["opcode"]] = InstructionSpec(
                opcode=entry["opcode"],
                operands=ops,
                unitary=entry["unitary"],
                semantics=str(entry["semantics"]).strip(),
                encoding=str(entry["encoding"]),
            )
        missing = set(_FALLBACK_TABLE) - set(self.instructions)
        if missing:
            raise ValueError(f"ISA spec missing opcodes: {sorted(missing)}")

    def _load_fallback(self) -> None:
        """Populate the instruction table from the vendored fallback."""
        self.meta = {"name": "QISA-K", "version": "0.1",
                     "classical_endianness": "little",
                     "source": "vendored fallback table (PyYAML absent)"}
        self.verifier_rules = {"errno_on_violation": "-ENOEXEC"}
        for opcode, (kinds, unitary) in _FALLBACK_TABLE.items():
            ops = tuple(
                OperandSpec(name=f"op{i}", kind=k) for i, k in enumerate(kinds)
            )
            self.instructions[opcode] = InstructionSpec(
                opcode=opcode, operands=ops, unitary=unitary,
                semantics="(fallback table; see QISA-v0.1.yaml)",
                encoding="(fallback table; see QISA-v0.1.yaml)",
            )

    def __contains__(self, opcode: str) -> bool:
        return opcode in self.instructions

    def __getitem__(self, opcode: str) -> InstructionSpec:
        return self.instructions[opcode]


# --------------------------------------------------------------------------
# Program representation + assembler (text loader)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Instruction:
    """One decoded program instruction.

    Attributes:
        opcode: Canonical QISA-K mnemonic (e.g. ``"CNOT"``).
        operands: Decoded operand values, positionally matching the ISA
            entry's operand list. Qubit/shadow/GPR operands are ints (the
            register index), angles are floats, immediates are ints, labels
            are strings.
        line_no: 1-based source line, for diagnostics.
        source: Original source text (comment stripped).
    """

    opcode: str
    operands: tuple[Any, ...]
    line_no: int
    source: str


@dataclass(frozen=True)
class Program:
    """A decoded QISA-K assembly program: instruction list + label map."""

    instructions: tuple[Instruction, ...]
    labels: dict[str, int]  # label name -> index into ``instructions``


def _parse_register(token: str, prefix: str, kind: str, line_no: int) -> int:
    """Parse a register token like ``q0`` / ``c1`` / ``r2`` into its index."""
    token = token.strip()
    if not token.startswith(prefix) or not token[len(prefix):].isdigit():
        raise QISAVerifierError(
            f"line {line_no}: expected {kind} register "
            f"('{prefix}<int>'), got {token!r}"
        )
    return int(token[len(prefix):])


def assemble(text: str, isa: ISA) -> Program:
    """Assemble QISA-K text into a :class:`Program`.

    Surface syntax follows the research doc's Bell-pair listing:

    * ``;`` starts a comment (rest of line ignored).
    * A token ending in ``:`` defines a label (e.g. ``.skip:``).
    * ``MEASURE q0 -> c0`` and ``FMR c0 -> r1`` use ``->``; all other
      multi-operand instructions are comma-separated (``CNOT q0, q1``;
      ``BRN r1, .skip``; ``RX q0, 3.14159``).

    Args:
        text: Assembly source text.
        isa: Loaded ISA table used for opcode/operand validation.

    Returns:
        The decoded program (instructions + label map).

    Raises:
        QISAVerifierError: On any malformed line -- the emulator-level
            analogue of the research doc's "malformed QIR" -ENOEXEC cause.
    """
    instructions: list[Instruction] = []
    labels: dict[str, int] = {}

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        # Label definition (possibly followed by an instruction on the line).
        while line and line.split()[0].endswith(":"):
            label = line.split()[0][:-1]
            if label in labels:
                raise QISAVerifierError(
                    f"line {line_no}: duplicate label {label!r}")
            labels[label] = len(instructions)
            line = line[len(label) + 1:].strip()
        if not line:
            continue

        parts = line.split(None, 1)
        opcode = parts[0].upper()
        if opcode not in isa:
            raise QISAVerifierError(
                f"line {line_no}: unknown opcode {parts[0]!r}")
        spec = isa[opcode]

        rest = parts[1] if len(parts) > 1 else ""
        # '->' and ',' are both operand separators ('MEASURE q -> c',
        # 'CNOT qc, qt').
        tokens = [t.strip() for t in rest.replace("->", ",").split(",")
                  if t.strip()]
        if len(tokens) != len(spec.operands):
            raise QISAVerifierError(
                f"line {line_no}: {opcode} expects {len(spec.operands)} "
                f"operand(s), got {len(tokens)}"
            )

        values: list[Any] = []
        for token, op_spec in zip(tokens, spec.operands):
            if op_spec.kind == "qubit":
                values.append(_parse_register(token, "q", "qubit", line_no))
            elif op_spec.kind == "shadow":
                values.append(_parse_register(token, "c", "shadow", line_no))
            elif op_spec.kind == "gpr":
                values.append(_parse_register(token, "r", "GPR", line_no))
            elif op_spec.kind == "angle":
                try:
                    values.append(float(token))
                except ValueError as exc:
                    raise QISAVerifierError(
                        f"line {line_no}: bad angle {token!r}") from exc
            elif op_spec.kind == "imm":
                try:
                    imm = int(token)
                except ValueError as exc:
                    raise QISAVerifierError(
                        f"line {line_no}: bad immediate {token!r}") from exc
                if imm < 0:
                    raise QISAVerifierError(
                        f"line {line_no}: negative immediate {imm}")
                values.append(imm)
            elif op_spec.kind == "label":
                values.append(token)
            else:  # pragma: no cover -- spec kinds are closed
                raise QISAVerifierError(
                    f"line {line_no}: unknown operand kind {op_spec.kind!r}")

        instructions.append(Instruction(
            opcode=opcode, operands=tuple(values),
            line_no=line_no, source=line,
        ))

    # Branch targets must exist (decode-time check).
    for ins in instructions:
        if ins.opcode == "BRN" and ins.operands[1] not in labels:
            raise QISAVerifierError(
                f"line {ins.line_no}: undefined label {ins.operands[1]!r}")

    return Program(instructions=tuple(instructions), labels=labels)


# --------------------------------------------------------------------------
# Classical register file
# --------------------------------------------------------------------------


@dataclass
class ClassicalRegisterFile:
    """Shadow registers ``c[]`` + GPRs ``r[]`` -- plain little-endian ints.

    Per the research doc's register model, this file is the ONLY part of the
    machine state that can be context-switched, copied, or swapped; all
    kernel-visible state lives here.

    Attributes:
        n_shadow: Number of shadow registers (c0 .. c{n-1}).
        n_gpr: Number of general-purpose registers (r0 .. r{n-1}).
    """

    n_shadow: int
    n_gpr: int = 8
    c: list[int] = field(default_factory=list)
    r: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        """Zero all classical registers (fresh-shot state)."""
        self.c = [0] * self.n_shadow
        self.r = [0] * self.n_gpr

    def snapshot(self) -> dict[str, int]:
        """Copy the shadow file as ``{"c0": v0, "c1": v1, ...}``.

        Copying is legal precisely because these registers are classical --
        the very operation that no-cloning [Proven] forbids for the quantum
        registers.
        """
        return {f"c{i}": v for i, v in enumerate(self.c)}


# --------------------------------------------------------------------------
# Gate matrices (exact, per the QISA-K spec)
# --------------------------------------------------------------------------

_SQRT1_2 = 1.0 / math.sqrt(2.0)

GATE_H: np.ndarray = np.array([[_SQRT1_2, _SQRT1_2],
                               [_SQRT1_2, -_SQRT1_2]], dtype=np.complex128)
GATE_X: np.ndarray = np.array([[0, 1], [1, 0]], dtype=np.complex128)
GATE_Y: np.ndarray = np.array([[0, -1j], [1j, 0]], dtype=np.complex128)
GATE_Z: np.ndarray = np.array([[1, 0], [0, -1]], dtype=np.complex128)
GATE_S: np.ndarray = np.array([[1, 0], [0, 1j]], dtype=np.complex128)
GATE_T: np.ndarray = np.array(
    [[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=np.complex128)

#: CNOT in (control, target) ordering, basis |c t>: |10> -> |11>, |11> -> |10>.
GATE_CNOT: np.ndarray = np.array([[1, 0, 0, 0],
                                  [0, 1, 0, 0],
                                  [0, 0, 0, 1],
                                  [0, 0, 1, 0]], dtype=np.complex128)
GATE_CZ: np.ndarray = np.diag([1, 1, 1, -1]).astype(np.complex128)


def gate_rx(theta: float) -> np.ndarray:
    """RX(theta) = exp(-i * theta/2 * X)."""
    c, s = math.cos(theta / 2.0), math.sin(theta / 2.0)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=np.complex128)


def gate_ry(theta: float) -> np.ndarray:
    """RY(theta) = exp(-i * theta/2 * Y)."""
    c, s = math.cos(theta / 2.0), math.sin(theta / 2.0)
    return np.array([[c, -s], [s, c]], dtype=np.complex128)


def gate_rz(theta: float) -> np.ndarray:
    """RZ(theta) = exp(-i * theta/2 * Z)."""
    return np.array([[np.exp(-1j * theta / 2.0), 0],
                     [0, np.exp(1j * theta / 2.0)]], dtype=np.complex128)


_FIXED_1Q_GATES: dict[str, np.ndarray] = {
    "H": GATE_H, "X": GATE_X, "Y": GATE_Y,
    "Z": GATE_Z, "S": GATE_S, "T": GATE_T,
}
_ROTATION_GATES = {"RX": gate_rx, "RY": gate_ry, "RZ": gate_rz}
_2Q_GATES: dict[str, np.ndarray] = {"CNOT": GATE_CNOT, "CZ": GATE_CZ}

#: Cap on emulated qubits: dense simulation stores 16 * 2**n bytes
#: (complex128), ~256 MB at n=24 (workflow, Prerequisites sizing note).
MAX_QUBITS: int = 24


# --------------------------------------------------------------------------
# The emulator
# --------------------------------------------------------------------------


class QCPU:
    """QISA-K quantum CPU emulator (dense NumPy statevector).

    Little-endian qubit ordering: qubit ``q`` is bit ``q`` of the basis-state
    index (q0 = least-significant bit). The statevector is ``complex128`` of
    length ``2**n_qubits``, initialized to |0...0>.

    Statistics counters (consumed by workflow Stage 5):
        * ``gate_counts``: executed-instruction histogram, per opcode.
        * ``two_qubit_gate_count``: CNOT + CZ executions.
        * ``measure_count``: MEASURE executions.
        * ``cycle_counter``: sum of QWAIT immediates. NOT a timing model --
          the counter exists only so Stage 5 can report simulated cycle
          totals (workflow Stage 2 step 5; Risk 3).
        * ``shot_count``: completed shots via :meth:`run_shots`.

    Args:
        n_qubits: Number of emulated qubits (1 .. 24).
        seed: Optional RNG seed for reproducible measurement sampling.
        isa: Optional pre-loaded :class:`ISA`; loaded from
            ``QISA-v0.1.yaml`` by default.

    Raises:
        ValueError: If ``n_qubits`` exceeds :data:`MAX_QUBITS` (the dense
            statevector would need ``16 * 2**n_qubits`` bytes).
    """

    def __init__(self, n_qubits: int, seed: int | None = None,
                 isa: ISA | None = None) -> None:
        if not 1 <= n_qubits <= MAX_QUBITS:
            raise ValueError(
                f"n_qubits={n_qubits} out of range 1..{MAX_QUBITS}: a dense "
                f"complex128 statevector costs 16 * 2**n bytes "
                f"({16 * 2 ** max(n_qubits, 0):,} bytes here); this is an "
                "emulator-capacity limit, not the [Proven] tomography bound"
            )
        self.n_qubits: int = n_qubits
        self.isa: ISA = isa if isa is not None else ISA()
        self.rng: np.random.Generator = np.random.default_rng(seed)
        self.creg: ClassicalRegisterFile = ClassicalRegisterFile(
            n_shadow=n_qubits)
        self.state: np.ndarray = np.zeros(2 ** n_qubits, dtype=np.complex128)
        self.state[0] = 1.0  # |0...0>

        # Statistics.
        self.gate_counts: dict[str, int] = {}
        self.two_qubit_gate_count: int = 0
        self.measure_count: int = 0
        self.cycle_counter: int = 0
        self.shot_count: int = 0

    # -- state management ---------------------------------------------------

    def reset_machine(self) -> None:
        """Return statevector and classical registers to power-on state.

        Statistics counters are deliberately NOT cleared -- they accumulate
        across shots (Stage 5 reports totals).
        """
        self.state[:] = 0.0
        self.state[0] = 1.0
        self.creg.clear()

    def _debug_statevector(self) -> np.ndarray:
        """TEST-ONLY copy of the raw amplitudes. Physically impossible.

        No real machine offers this: reading quantum state non-destructively
        is excluded by the measurement postulate [Proven], and copying it by
        no-cloning [Proven] (research doc, memory-model invariants 1-2). It
        exists solely so tests can check gate semantics; nothing in the
        emulator's "kernel-visible" path (MEASURE -> shadow -> FMR) uses it.
        """
        return self.state.copy()

    # -- unitary application (reshape/tensordot, no 2**n x 2**n Kronecker) --

    def _axis(self, q: int) -> int:
        """Tensor axis for qubit ``q`` under little-endian ordering.

        Reshaping the length-2**n vector to shape (2,)*n makes axis 0 the
        MOST-significant bit, i.e. qubit n-1; qubit q is axis n-1-q.
        """
        return self.n_qubits - 1 - q

    def apply_1q(self, gate_matrix: np.ndarray, q: int) -> None:
        """Apply a 2x2 unitary to qubit ``q`` in place."""
        psi = self.state.reshape((2,) * self.n_qubits)
        ax = self._axis(q)
        psi = np.moveaxis(psi, ax, 0)
        psi = np.tensordot(gate_matrix, psi, axes=([1], [0]))
        psi = np.moveaxis(psi, 0, ax)
        self.state = np.ascontiguousarray(psi).reshape(-1)

    def apply_2q(self, gate_matrix: np.ndarray, qc: int, qt: int) -> None:
        """Apply a 4x4 unitary (basis |qc qt>) to qubits ``qc``, ``qt``."""
        psi = self.state.reshape((2,) * self.n_qubits)
        axc, axt = self._axis(qc), self._axis(qt)
        psi = np.moveaxis(psi, (axc, axt), (0, 1))
        g = gate_matrix.reshape(2, 2, 2, 2)
        psi = np.tensordot(g, psi, axes=([2, 3], [0, 1]))
        psi = np.moveaxis(psi, (0, 1), (axc, axt))
        self.state = np.ascontiguousarray(psi).reshape(-1)

    # -- non-unitary ops ------------------------------------------------------

    def _sample_and_project(self, q: int) -> int:
        """Sample qubit ``q`` in the Z basis, project, renormalize.

        Returns the classical outcome (0 or 1). This is the destructive
        collapse of the measurement postulate [Proven]; there is no peeking
        API (research doc, memory-model invariant 2).
        """
        psi = self.state.reshape((2,) * self.n_qubits)
        ax = self._axis(q)
        psi = np.moveaxis(psi, ax, 0)
        p1 = float(np.sum(np.abs(psi[1]) ** 2))
        outcome = 1 if self.rng.random() < p1 else 0
        psi[1 - outcome] = 0.0
        norm = math.sqrt(p1 if outcome == 1 else max(1.0 - p1, 0.0))
        if norm > 0.0:
            psi /= norm
        psi = np.moveaxis(psi, 0, ax)
        self.state = np.ascontiguousarray(psi).reshape(-1)
        return outcome

    def measure(self, q: int, c: int) -> int:
        """MEASURE q -> c: project to Z basis, write outcome to shadow ``c``.

        Destructive: superposition on ``q`` is destroyed (measurement
        postulate [Proven]). Returns the outcome bit.
        """
        outcome = self._sample_and_project(q)
        self.creg.c[c] = outcome
        return outcome

    def reset(self, q: int) -> None:
        """RESET q: active reset to |0> -- measure + conditional X.

        Matches the spec's RESET semantics ("measure + conditional X",
        research doc QISA table). The internal measurement consumes one RNG
        draw but writes no shadow register.
        """
        if self._sample_and_project(q) == 1:
            self.apply_1q(GATE_X, q)

    # -- classical side -------------------------------------------------------

    def fmr(self, c: int, r: int) -> None:
        """FMR c -> r: fetch measurement result into the classical pipeline."""
        self.creg.r[r] = self.creg.c[c]

    def qwait(self, cycles: int) -> None:
        """QWAIT: advance the simulated cycle counter.

        Not timing-accurate -- the counter exists so Stage 5 can report
        simulated cycle totals (workflow Stage 2 step 5).
        """
        self.cycle_counter += cycles

    # -- program loading / verification / execution ---------------------------

    def load_program(self, text: str) -> Program:
        """Assemble QISA-K text into a verified-decodable :class:`Program`."""
        return assemble(text, self.isa)

    def verify(self, program: Program) -> None:
        """Statically enforce the Stage 1 verifier rules BEFORE execution.

        Implements the ``verifier_rules`` of QISA-v0.1.yaml -- the research
        doc's -ENOEXEC conditions, checked over the instruction sequence in
        program order (conservative w.r.t. branches):

        * ``no-gate-on-unleased-qubit``: every qubit operand must satisfy
          0 <= index < n_qubits (the emulator's "lease" is its register
          file).
        * ``malformed-program``: shadow (``c*``) and GPR (``r*``) operand
          indices must name an existing classical register -- an
          out-of-range index is the statically checkable slice of the
          research doc's "malformed QIR" -ENOEXEC cause.
        * ``no-use-after-measure-without-RESET``: after MEASURE q, any gate
          or MEASURE on q without an intervening RESET is rejected -- the
          quantum analogue of W^X enforcement (research doc, Bell-listing
          commentary).
        * ``no-qubit-operand-duplication-in-copy-position``: rejects e.g.
          ``CNOT q0, q0`` (workflow Stage 1 addition; linear-resource
          discipline).

        Raises:
            QISAVerifierError: With ``errno == -ENOEXEC`` on any violation.
        """
        measured: set[int] = set()
        for ins in program.instructions:
            spec = self.isa[ins.opcode]
            qubits = [v for v, o in zip(ins.operands, spec.operands)
                      if o.kind == "qubit"]
            for q in qubits:
                if not 0 <= q < self.n_qubits:
                    raise QISAVerifierError(
                        f"line {ins.line_no}: gate on unleased qubit q{q} "
                        f"(lease covers q0..q{self.n_qubits - 1})",
                        rule="no-gate-on-unleased-qubit",
                    )
            if len(qubits) == 2 and qubits[0] == qubits[1]:
                raise QISAVerifierError(
                    f"line {ins.line_no}: {ins.opcode} q{qubits[0]}, "
                    f"q{qubits[1]} duplicates a qubit operand",
                    rule="no-qubit-operand-duplication-in-copy-position",
                )
            for v, o in zip(ins.operands, spec.operands):
                if o.kind == "shadow" and not 0 <= v < self.creg.n_shadow:
                    raise QISAVerifierError(
                        f"line {ins.line_no}: shadow register c{v} out of "
                        f"range", rule="malformed-program")
                if o.kind == "gpr" and not 0 <= v < self.creg.n_gpr:
                    raise QISAVerifierError(
                        f"line {ins.line_no}: GPR r{v} out of range",
                        rule="malformed-program")

            if ins.opcode == "RESET":
                measured.discard(qubits[0])
            elif ins.opcode == "MEASURE":
                if qubits[0] in measured:
                    raise QISAVerifierError(
                        f"line {ins.line_no}: MEASURE on q{qubits[0]} after "
                        "MEASURE without RESET (use-after-measure)",
                        rule="no-use-after-measure-without-RESET",
                    )
                measured.add(qubits[0])
            elif spec.unitary:
                for q in qubits:
                    if q in measured:
                        raise QISAVerifierError(
                            f"line {ins.line_no}: {ins.opcode} on q{q} after "
                            "MEASURE without RESET (use-after-measure)",
                            rule="no-use-after-measure-without-RESET",
                        )

    def _execute(self, ins: Instruction, program: Program,
                 pc: int) -> int:
        """Execute one instruction; return the next program counter."""
        op = ins.opcode
        self.gate_counts[op] = self.gate_counts.get(op, 0) + 1
        if op in _FIXED_1Q_GATES:
            self.apply_1q(_FIXED_1Q_GATES[op], ins.operands[0])
        elif op in _ROTATION_GATES:
            q, theta = ins.operands
            self.apply_1q(_ROTATION_GATES[op](theta), q)
        elif op in _2Q_GATES:
            self.apply_2q(_2Q_GATES[op], ins.operands[0], ins.operands[1])
            self.two_qubit_gate_count += 1
        elif op == "MEASURE":
            self.measure(ins.operands[0], ins.operands[1])
            self.measure_count += 1
        elif op == "RESET":
            self.reset(ins.operands[0])
        elif op == "FMR":
            self.fmr(ins.operands[0], ins.operands[1])
        elif op == "QWAIT":
            self.qwait(ins.operands[0])
        elif op == "BRN":
            reg, label = ins.operands
            if self.creg.r[reg] != 0:  # branch-if-nonzero (QISA-v0.1.yaml)
                return program.labels[label]
        else:  # pragma: no cover -- ISA table is closed
            raise QISAVerifierError(f"unimplemented opcode {op!r}")
        return pc + 1

    def run(self, program: Program | str) -> dict[str, int]:
        """Verify, then execute one shot of ``program`` on the current state.

        The verifier runs BEFORE execution (workflow Stage 2 step 6); a
        rejected program leaves the machine untouched.

        Args:
            program: A decoded :class:`Program`, or assembly text (assembled
                on the fly).

        Returns:
            Snapshot of the shadow register file after the shot -- the only
            kernel-visible artifact of the program (research doc, Bell
            listing: "c0, c1 are the ONLY kernel-visible artifacts").
        """
        if isinstance(program, str):
            program = self.load_program(program)
        self.verify(program)
        pc = 0
        while 0 <= pc < len(program.instructions):
            pc = self._execute(program.instructions[pc], program, pc)
        return self.creg.snapshot()

    def run_shots(self, program: Program | str,
                  shots: int) -> list[dict[str, int]]:
        """Run ``program`` for ``shots`` independent shots.

        Each shot starts from a fresh |0...0> state and cleared classical
        registers; the seeded RNG stream continues across shots, so results
        are reproducible for a given ``seed``. Shots are statistically
        independent trials, not cooperating threads (research doc, mapping
        table: no shared mutable memory between shots).

        Args:
            program: Decoded program or assembly text.
            shots: Number of shots (>= 1).

        Returns:
            One shadow-register snapshot per shot.
        """
        if isinstance(program, str):
            program = self.load_program(program)
        if shots < 1:
            raise ValueError("shots must be >= 1")
        results: list[dict[str, int]] = []
        for _ in range(shots):
            self.reset_machine()
            results.append(self.run(program))
            self.shot_count += 1
        return results

    def stats(self) -> dict[str, Any]:
        """Aggregate gate-count / shot statistics (workflow Stage 2 step 7)."""
        return {
            "gate_counts": dict(self.gate_counts),
            "two_qubit_gate_count": self.two_qubit_gate_count,
            "measure_count": self.measure_count,
            "cycle_counter": self.cycle_counter,
            "shot_count": self.shot_count,
        }


# --------------------------------------------------------------------------
# Canonical programs (shared with the test suite)
# --------------------------------------------------------------------------

#: Hello-quantum: prepare |1>, measure -- c0 == 1 every shot.
HELLO_QUANTUM_ASM: str = """\
; hello-quantum: deterministic |1> preparation
        RESET   q0
        X       q0
        MEASURE q0 -> c0
"""

#: The UNCORRECTED Bell circuit -- the research doc's listing with the
#: FMR/BRN/X feed-forward path removed (workflow Stage 2 step 8). Outcomes
#: are perfectly correlated: c0 == c1 in every shot.
BELL_UNCORRECTED_ASM: str = """\
; uncorrected Bell pair: (|00> + |11>)/sqrt(2), both halves measured
        RESET   q0
        RESET   q1
        H       q0
        CNOT    q0, q1
        MEASURE q0 -> c0
        MEASURE q1 -> c1
"""

#: The research doc's Bell-pair-with-feed-forward listing, assembled verbatim
#: (docs/research/02-quantum-linux.md, "Example: Bell pair with feed-forward
#: in QISA-K"). The conditional-X correction is the teleportation
#: disentangling step, so c1 is constant across shots while c0 stays ~50/50;
#: c0 == c1 does NOT hold here.
BELL_FEEDFORWARD_ASM: str = """\
; lease assumed: q0, q1 mapped by the kernel's virtual->physical qubit table
        RESET   q0              ; non-unitary: active |0> preparation
        RESET   q1
        QWAIT   12              ; deterministic cycle alignment (eQASM-style)
        H       q0              ; q0 -> (|0> + |1>)/sqrt(2)
        CNOT    q0, q1          ; entangle: (|00> + |11>)/sqrt(2)
        MEASURE q0 -> c0        ; destructive: collapses the pair
        FMR     c0 -> r1        ; shadow register into classical pipeline
        BRN     r1, .skip       ; classical branch on outcome (real-time path)
        X       q1              ; conditional correction
.skip:
        MEASURE q1 -> c1
        ; c0, c1 are the ONLY kernel-visible artifacts of this program
"""


def _demo(shots: int = 1024, seed: int = 42) -> None:
    """Run the canonical programs and print shot histograms + statistics."""
    print(f"QISA-K emulator demo (seed={seed}, shots={shots})")
    for name, asm in [("hello-quantum", HELLO_QUANTUM_ASM),
                      ("bell-uncorrected", BELL_UNCORRECTED_ASM),
                      ("bell-feed-forward", BELL_FEEDFORWARD_ASM)]:
        cpu = QCPU(n_qubits=2, seed=seed)
        results = cpu.run_shots(asm, shots)
        hist: dict[str, int] = {}
        for snap in results:
            key = f"c1={snap['c1']} c0={snap['c0']}"
            hist[key] = hist.get(key, 0) + 1
        print(f"\n[{name}] ISA loaded from "
              f"{'YAML' if cpu.isa.loaded_from_yaml else 'fallback table'}")
        for key in sorted(hist):
            print(f"  {key}: {hist[key]:5d} ({hist[key] / shots:6.1%})")
        print(f"  stats: {cpu.stats()}")


if __name__ == "__main__":
    _demo()
