"""Stage 2 test suite for the QISA-K emulator (workflow Stage 2 step 8).

Tests, per docs/workflows/02-linux-workflow.md and the research doc
(docs/research/02-quantum-linux.md, QISA section):

* hello-quantum -- prepare |1>, measure, expect c0 == 1 in every shot.
* Correlation test -- the UNCORRECTED Bell circuit (the research doc's
  listing with the FMR/BRN/X feed-forward path removed): c0 == c1 in every
  shot, c0 marginal ~50/50 within 5 sigma.
* Feed-forward determinism test -- the research doc's Bell-pair-with-
  feed-forward listing assembled verbatim: c1 is the SAME constant value in
  every shot (the conditional-X correction is the teleportation
  disentangling step), c0 marginal ~50/50 within 5 sigma. c0 == c1 does NOT
  hold here and is deliberately not asserted.
* Gate-decode tests for every QISA-K opcode (H, X, Y, Z, S, T, RX, RY, RZ,
  CNOT, CZ, MEASURE, RESET, FMR, QWAIT, BRN).
* Verifier (-ENOEXEC) tests -- use-after-measure without RESET, gate on an
  unleased qubit, and qubit-operand duplication all raise QISAVerifierError
  with errno == -ENOEXEC.

Statistical tolerance: with N = 4096 shots and p = 0.5, sigma =
sqrt(N * p * (1-p)) = 32, so the 5-sigma window on the ones-count is
2048 +/- 160. Tests are seeded, hence deterministic.

Run with: /tmp/qhr-venv/bin/python -m pytest quantum-linux/emulator/
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from qcpu import (
    BELL_FEEDFORWARD_ASM,
    BELL_UNCORRECTED_ASM,
    ENOEXEC,
    HELLO_QUANTUM_ASM,
    ISA,
    MAX_QUBITS,
    QCPU,
    QISAVerifierError,
)

SHOTS: int = 4096
SEED: int = 1234

#: 5-sigma window on the count of ones for p = 0.5 (workflow Stage 2 step 8).
_SIGMA: float = math.sqrt(SHOTS * 0.25)
_FIVE_SIGMA: float = 5.0 * _SIGMA

#: All 15 opcodes of the research doc's QISA table, plus BRN (the workflow's
#: classical control-flow addition). Diffing against the research doc must
#: show no renames, no extra additions, no missing entries.
ALL_OPCODES: tuple[str, ...] = (
    "H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ",
    "CNOT", "CZ", "MEASURE", "RESET", "FMR", "QWAIT", "BRN",
)

_SQRT1_2 = 1.0 / math.sqrt(2.0)


def _cpu(n_qubits: int = 2, seed: int = SEED) -> QCPU:
    """Fresh seeded emulator instance."""
    return QCPU(n_qubits=n_qubits, seed=seed)


def _assert_close(state: np.ndarray, expected: list[complex]) -> None:
    """Assert statevector amplitudes match ``expected`` elementwise."""
    np.testing.assert_allclose(state, np.array(expected, dtype=np.complex128),
                               atol=1e-12)


# ===========================================================================
# Hello-quantum
# ===========================================================================


class TestHelloQuantum:
    """Prepare |1>, measure: c0 == 1, deterministically, every shot."""

    def test_c0_is_one_every_shot(self) -> None:
        cpu = _cpu(n_qubits=1)
        results = cpu.run_shots(HELLO_QUANTUM_ASM, SHOTS)
        assert len(results) == SHOTS
        assert all(snap["c0"] == 1 for snap in results)

    def test_seeded_runs_are_reproducible(self) -> None:
        """Same seed => identical shot sequence (RNG support requirement)."""
        a = _cpu().run_shots(BELL_UNCORRECTED_ASM, 256)
        b = _cpu().run_shots(BELL_UNCORRECTED_ASM, 256)
        assert a == b


# ===========================================================================
# Correlation test: UNCORRECTED Bell circuit
# ===========================================================================


class TestBellUncorrectedCorrelation:
    """(|00> + |11>)/sqrt(2) measured on both halves: perfect correlation."""

    @pytest.fixture(scope="class")
    def results(self) -> list[dict[str, int]]:
        return _cpu().run_shots(BELL_UNCORRECTED_ASM, SHOTS)

    def test_c0_equals_c1_every_shot(self,
                                     results: list[dict[str, int]]) -> None:
        """Entanglement correlation: c0 == c1 in ALL 4096 shots."""
        assert all(snap["c0"] == snap["c1"] for snap in results)

    def test_c0_marginal_is_uniform_within_5_sigma(
            self, results: list[dict[str, int]]) -> None:
        """The c0 marginal is ~50/50 (within 5 sigma of N/2)."""
        ones = sum(snap["c0"] for snap in results)
        assert abs(ones - SHOTS / 2) <= _FIVE_SIGMA, (
            f"c0 marginal {ones}/{SHOTS} outside 5-sigma window")

    def test_both_outcomes_observed(self,
                                    results: list[dict[str, int]]) -> None:
        """Sanity: the distribution is genuinely random, not constant."""
        values = {snap["c0"] for snap in results}
        assert values == {0, 1}


# ===========================================================================
# Feed-forward determinism test: the research doc's listing, verbatim
# ===========================================================================


class TestBellFeedForwardDeterminism:
    """The conditional-X correction makes q1 collapse deterministically.

    Per the workflow (Stage 2 step 8): c1 must be the SAME constant value in
    every shot, while the c0 marginal stays ~50/50. c0 == c1 does NOT hold
    here and must not be asserted.
    """

    @pytest.fixture(scope="class")
    def results(self) -> list[dict[str, int]]:
        return _cpu().run_shots(BELL_FEEDFORWARD_ASM, SHOTS)

    def test_c1_is_constant_every_shot(self,
                                       results: list[dict[str, int]]) -> None:
        """Feed-forward determinism: exactly one distinct c1 value."""
        assert len(results) >= 1024  # assignment floor; we run 4096
        c1_values = {snap["c1"] for snap in results}
        assert len(c1_values) == 1
        # Under BRN's branch-if-nonzero semantics (QISA-v0.1.yaml), the X
        # correction fires on outcome 0, so the constant is 1.
        assert c1_values == {1}

    def test_c0_marginal_is_uniform_within_5_sigma(
            self, results: list[dict[str, int]]) -> None:
        """c0 (the collapsing measurement) stays ~50/50 within 5 sigma."""
        ones = sum(snap["c0"] for snap in results)
        assert abs(ones - SHOTS / 2) <= _FIVE_SIGMA, (
            f"c0 marginal {ones}/{SHOTS} outside 5-sigma window")

    def test_conditional_x_fires_only_on_zero_outcomes(self) -> None:
        """The X correction count equals the number of c0 == 0 shots."""
        cpu = _cpu()
        results = cpu.run_shots(BELL_FEEDFORWARD_ASM, 512)
        zeros = sum(1 for snap in results if snap["c0"] == 0)
        assert cpu.gate_counts.get("X", 0) == zeros


# ===========================================================================
# ISA completeness + gate decode for every opcode
# ===========================================================================


class TestISACompleteness:
    """The loaded ISA matches the research doc's QISA table exactly."""

    @pytest.fixture(scope="class")
    def isa(self) -> ISA:
        return ISA()

    def test_loads_from_yaml(self, isa: ISA) -> None:
        """PyYAML is installed in the verify venv; the YAML path is used."""
        assert isa.loaded_from_yaml
        assert isa.meta["name"] == "QISA-K"
        assert str(isa.meta["version"]) == "0.1"
        assert isa.meta["classical_endianness"] == "little"

    def test_all_16_opcodes_present_no_extras(self, isa: ISA) -> None:
        assert set(isa.instructions) == set(ALL_OPCODES)

    @pytest.mark.parametrize("opcode", ALL_OPCODES)
    def test_every_opcode_has_unitary_and_encoding(self, isa: ISA,
                                                   opcode: str) -> None:
        spec = isa[opcode]
        assert spec.unitary in (True, False, None)  # None == "n/a"
        assert spec.encoding  # non-empty encoding sketch
        assert spec.semantics

    def test_unitary_flags_match_research_doc(self, isa: ISA) -> None:
        """Unitary column of the research doc's table, opcode by opcode."""
        unitary = {"H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ",
                   "CNOT", "CZ"}
        non_unitary = {"MEASURE", "RESET"}
        classical = {"FMR", "QWAIT", "BRN"}  # "n/a" in the table
        for op in unitary:
            assert isa[op].unitary is True, op
        for op in non_unitary:
            assert isa[op].unitary is False, op
        for op in classical:
            assert isa[op].unitary is None, op

    def test_fallback_table_matches_yaml(self, isa: ISA) -> None:
        """The vendored no-PyYAML fallback stays in sync with the YAML."""
        from qcpu import _FALLBACK_TABLE
        assert set(_FALLBACK_TABLE) == set(isa.instructions)
        for op, (kinds, unitary) in _FALLBACK_TABLE.items():
            spec = isa[op]
            assert tuple(o.kind for o in spec.operands) == kinds, op
            assert spec.unitary == unitary, op


class TestGateDecodeAndSemantics:
    """Decode + execute every opcode; check exact statevector semantics.

    Statevector checks use the test-only ``_debug_statevector()`` accessor,
    which no physical machine offers (measurement postulate [Proven]) --
    see its docstring in qcpu.py. Little-endian ordering: q0 is bit 0 of
    the basis index, so |q1 q0> = |01> is index 1.
    """

    DECODE_CASES: tuple[tuple[str, str, tuple, ...], ...] = (
        ("H", "H q0", (0,)),
        ("X", "X q1", (1,)),
        ("Y", "Y q0", (0,)),
        ("Z", "Z q0", (0,)),
        ("S", "S q0", (0,)),
        ("T", "T q0", (0,)),
        ("RX", "RX q0, 1.5707963", (0, 1.5707963)),
        ("RY", "RY q0, 3.14159", (0, 3.14159)),
        ("RZ", "RZ q1, 0.5", (1, 0.5)),
        ("CNOT", "CNOT q0, q1", (0, 1)),
        ("CZ", "CZ q0, q1", (0, 1)),
        ("MEASURE", "MEASURE q0 -> c0", (0, 0)),
        ("RESET", "RESET q1", (1,)),
        ("FMR", "FMR c0 -> r1", (0, 1)),
        ("QWAIT", "QWAIT 12", (12,)),
        ("BRN", "end: BRN r0, end", (0, "end")),
    )

    @pytest.mark.parametrize("opcode,asm,operands", DECODE_CASES,
                             ids=[c[0] for c in DECODE_CASES])
    def test_decode_every_opcode(self, opcode: str, asm: str,
                                 operands: tuple) -> None:
        """Each opcode assembles to the right mnemonic + operand values."""
        cpu = _cpu()
        program = cpu.load_program(asm)
        assert len(program.instructions) == 1
        ins = program.instructions[0]
        assert ins.opcode == opcode
        if all(isinstance(v, (int, float)) for v in operands):
            assert ins.operands == pytest.approx(operands)
        else:
            assert ins.operands == operands

    def test_decode_case_insensitive_mnemonics(self) -> None:
        cpu = _cpu()
        program = cpu.load_program("cnot q0, q1")
        assert program.instructions[0].opcode == "CNOT"

    # -- per-gate semantic checks ------------------------------------------

    def test_h_semantics(self) -> None:
        cpu = _cpu(1)
        cpu.run("H q0")
        _assert_close(cpu._debug_statevector(), [_SQRT1_2, _SQRT1_2])

    def test_x_semantics(self) -> None:
        cpu = _cpu(1)
        cpu.run("X q0")
        _assert_close(cpu._debug_statevector(), [0, 1])

    def test_y_semantics(self) -> None:
        cpu = _cpu(1)
        cpu.run("Y q0")
        _assert_close(cpu._debug_statevector(), [0, 1j])

    def test_z_semantics(self) -> None:
        cpu = _cpu(1)
        cpu.run("H q0\nZ q0")
        _assert_close(cpu._debug_statevector(), [_SQRT1_2, -_SQRT1_2])

    def test_s_semantics(self) -> None:
        cpu = _cpu(1)
        cpu.run("H q0\nS q0")
        _assert_close(cpu._debug_statevector(), [_SQRT1_2, 1j * _SQRT1_2])

    def test_t_semantics(self) -> None:
        cpu = _cpu(1)
        cpu.run("H q0\nT q0")
        phase = complex(np.exp(1j * np.pi / 4))
        _assert_close(cpu._debug_statevector(),
                      [_SQRT1_2, phase * _SQRT1_2])

    def test_rx_pi_semantics(self) -> None:
        """RX(pi)|0> = -i|1>."""
        cpu = _cpu(1)
        cpu.run(f"RX q0, {math.pi}")
        _assert_close(cpu._debug_statevector(), [0, -1j])

    def test_ry_pi_semantics(self) -> None:
        """RY(pi)|0> = |1>."""
        cpu = _cpu(1)
        cpu.run(f"RY q0, {math.pi}")
        _assert_close(cpu._debug_statevector(), [0, 1])

    def test_rz_semantics(self) -> None:
        """RZ(theta) on H|0> applies opposite half-phases to |0>, |1>."""
        theta = math.pi / 3
        cpu = _cpu(1)
        cpu.run(f"H q0\nRZ q0, {theta}")
        e0 = complex(np.exp(-1j * theta / 2)) * _SQRT1_2
        e1 = complex(np.exp(+1j * theta / 2)) * _SQRT1_2
        _assert_close(cpu._debug_statevector(), [e0, e1])

    def test_cnot_semantics(self) -> None:
        """X q0; CNOT q0,q1: |01> -> |11> (little-endian: index 1 -> 3)."""
        cpu = _cpu(2)
        cpu.run("X q0\nCNOT q0, q1")
        _assert_close(cpu._debug_statevector(), [0, 0, 0, 1])

    def test_cnot_control_zero_is_identity(self) -> None:
        cpu = _cpu(2)
        cpu.run("CNOT q0, q1")
        _assert_close(cpu._debug_statevector(), [1, 0, 0, 0])

    def test_cz_semantics(self) -> None:
        """CZ flips the sign of the |11> amplitude only."""
        cpu = _cpu(2)
        cpu.run("X q0\nX q1\nCZ q0, q1")
        _assert_close(cpu._debug_statevector(), [0, 0, 0, -1])

    def test_measure_semantics_deterministic(self) -> None:
        """MEASURE on |1> writes 1 to the shadow register, every time."""
        cpu = _cpu(1)
        snap = cpu.run("X q0\nMEASURE q0 -> c0")
        assert snap["c0"] == 1
        _assert_close(cpu._debug_statevector(), [0, 1])  # projected, not gone

    def test_reset_semantics(self) -> None:
        """RESET returns an excited qubit to |0> (measure + conditional X)."""
        cpu = _cpu(1)
        cpu.run("X q0\nRESET q0")
        _assert_close(cpu._debug_statevector(), [1, 0])

    def test_fmr_semantics(self) -> None:
        """FMR copies a shadow bit into the classical (GPR) pipeline."""
        cpu = _cpu(1)
        cpu.run("X q0\nMEASURE q0 -> c0\nFMR c0 -> r1")
        assert cpu.creg.r[1] == 1

    def test_qwait_semantics(self) -> None:
        """QWAIT advances the (non-timing-accurate) cycle counter."""
        cpu = _cpu(1)
        cpu.run("QWAIT 12\nQWAIT 30")
        assert cpu.cycle_counter == 42

    def test_brn_taken_and_not_taken(self) -> None:
        """BRN branches iff the GPR is nonzero (branch-if-nonzero)."""
        # Not taken: r1 == 0 (q0 measured in |0>), so X q1 executes.
        cpu = _cpu(2)
        snap = cpu.run(
            "MEASURE q0 -> c0\nFMR c0 -> r1\nBRN r1, done\nX q1\n"
            "done: MEASURE q1 -> c1")
        assert snap == {"c0": 0, "c1": 1}
        # Taken: r1 == 1 (q0 prepared in |1>), so X q1 is skipped.
        cpu = _cpu(2)
        snap = cpu.run(
            "X q0\nMEASURE q0 -> c0\nFMR c0 -> r1\nBRN r1, done\nX q1\n"
            "done: MEASURE q1 -> c1")
        assert snap == {"c0": 1, "c1": 0}

    def test_gate_count_statistics(self) -> None:
        """gate_counts / two_qubit_gate_count / measure_count accumulate."""
        cpu = _cpu(2)
        cpu.run_shots(BELL_UNCORRECTED_ASM, 8)
        stats = cpu.stats()
        assert stats["gate_counts"]["H"] == 8
        assert stats["gate_counts"]["CNOT"] == 8
        assert stats["gate_counts"]["RESET"] == 16
        assert stats["two_qubit_gate_count"] == 8
        assert stats["measure_count"] == 16
        assert stats["shot_count"] == 8


# ===========================================================================
# Verifier (-ENOEXEC) tests
# ===========================================================================


class TestVerifierENOEXEC:
    """Static verifier rejections -- the research doc's -ENOEXEC conditions.

    Errno table row (research doc, syscall section): -ENOEXEC = "Verifier
    rejection: unleased qubit, use-after-measure, or malformed QIR".
    """

    #: Deliberately corrupted program: H q0 after MEASURE q0, no RESET --
    #: the workflow's canonical verifier test (Stage 2 step 8).
    USE_AFTER_MEASURE_ASM = """\
        RESET   q0
        H       q0
        MEASURE q0 -> c0
        H       q0              ; use-after-measure: REJECT
"""

    def test_use_after_measure_raises_enoexec(self) -> None:
        cpu = _cpu(1)
        with pytest.raises(QISAVerifierError) as excinfo:
            cpu.run(self.USE_AFTER_MEASURE_ASM)
        assert excinfo.value.errno == -ENOEXEC == -8
        assert excinfo.value.rule == "no-use-after-measure-without-RESET"

    def test_reset_clears_use_after_measure(self) -> None:
        """An intervening RESET makes re-use legal again."""
        cpu = _cpu(1)
        snap = cpu.run("H q0\nMEASURE q0 -> c0\nRESET q0\nH q0\n"
                       "RESET q0\nMEASURE q0 -> c0")
        assert snap["c0"] == 0

    def test_double_measure_without_reset_raises(self) -> None:
        cpu = _cpu(1)
        with pytest.raises(QISAVerifierError) as excinfo:
            cpu.run("H q0\nMEASURE q0 -> c0\nMEASURE q0 -> c0")
        assert excinfo.value.errno == -ENOEXEC

    def test_unleased_qubit_raises_enoexec(self) -> None:
        """Gate on a qubit outside the lease (q5 on a 2-qubit machine)."""
        cpu = _cpu(2)
        with pytest.raises(QISAVerifierError) as excinfo:
            cpu.run("H q5")
        assert excinfo.value.errno == -ENOEXEC
        assert excinfo.value.rule == "no-gate-on-unleased-qubit"

    def test_qubit_operand_duplication_raises_enoexec(self) -> None:
        """CNOT q0, q0 violates the linear-resource discipline."""
        cpu = _cpu(2)
        with pytest.raises(QISAVerifierError) as excinfo:
            cpu.run("CNOT q0, q0")
        assert excinfo.value.errno == -ENOEXEC
        assert (excinfo.value.rule
                == "no-qubit-operand-duplication-in-copy-position")

    def test_verifier_rejects_before_executing_anything(self) -> None:
        """A rejected program leaves the machine untouched (verify-first)."""
        cpu = _cpu(1)
        with pytest.raises(QISAVerifierError):
            cpu.run("X q0\nMEASURE q0 -> c0\nH q0")
        # The X before the faulty line must NOT have executed.
        _assert_close(cpu._debug_statevector(), [1, 0])
        assert cpu.gate_counts == {}

    def test_malformed_program_raises_enoexec(self) -> None:
        """Decode failures map to the 'malformed QIR' -ENOEXEC cause."""
        cpu = _cpu(1)
        with pytest.raises(QISAVerifierError) as excinfo:
            cpu.load_program("FROBNICATE q0")
        assert excinfo.value.errno == -ENOEXEC

    def test_undefined_branch_label_raises(self) -> None:
        cpu = _cpu(1)
        with pytest.raises(QISAVerifierError):
            cpu.load_program("BRN r0, .nowhere")

    def test_qubit_cap_cites_memory_cost(self) -> None:
        """n_qubits > 24 fails with the 16 * 2**n capacity rationale."""
        with pytest.raises(ValueError, match=r"16 \* 2\*\*n"):
            QCPU(n_qubits=MAX_QUBITS + 1)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
