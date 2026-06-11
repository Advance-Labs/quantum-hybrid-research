"""Tests for the QLOS toolchain (qas assembler + qdis disassembler).

Covers the BINDING contracts of quantum-linux/qos/QLOS-DESIGN-v0.1.md:

* section 6.2 -- QOBJ v0.1 envelope schema, requirements minimums, static
  stats (distinct from QCPU's runtime counters), source hash;
* section 6.3 -- load-time protection (every error class rejects at
  assemble time with a source line number and ``errno == -ENOEXEC``) and
  the round-trip law ``assemble(disassemble(q))`` -> identical
  instructions/labels/requirements/stats;
* sections 8.1-8.2 -- the public API surface and CLI behavior.

Everything exercised here is classical tooling over circuit descriptions
(ordinary files, per the research doc's VFS audit); the only quantum
content is the final integration check that toolchain output drives the
``qcpu`` statevector emulator correctly.

Run: /tmp/qhr-venv/bin/python -m pytest quantum-linux/toolchain/
"""

from __future__ import annotations

import errno
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "emulator"))

import qcpu
import qas
import qdis

ENOEXEC = errno.ENOEXEC

#: One program exercising every QISA-K v0.1 opcode exactly where legal
#: (use-after-measure rules respected; CNOT/CZ on distinct qubits).
ALL_OPCODES_ASM = """\
; all-opcodes exercise program (test fixture)
        RESET   q0
        RESET   q1
        H       q0
        X       q0
        Y       q0
        Z       q0
        S       q0
        T       q0
        RX      q0, 0.5
        RY      q0, 0.25
        RZ      q0, 1.5707963
        CNOT    q0, q1
        CZ      q1, q0
        QWAIT   12
        MEASURE q0 -> c0
        FMR     c0 -> r1
        BRN     r1, .skip
        X       q1
.skip:
        MEASURE q1 -> c1
"""

CANONICAL_SOURCES = {
    "hello": qcpu.HELLO_QUANTUM_ASM,
    "bell-uncorrected": qcpu.BELL_UNCORRECTED_ASM,
    "bell-feed-forward": qcpu.BELL_FEEDFORWARD_ASM,
    "all-opcodes": ALL_OPCODES_ASM,
    "empty": "; nothing but a comment\n\n",
    "label-first-line": "start: H q0\nFMR c0 -> r0\nBRN r0, start\n",
    "trailing-label": "        FMR c0 -> r0\n        BRN r0, .end\n.end:\n",
}


def assert_round_trip_equal(a: qas.QObj, b: qas.QObj) -> None:
    """Assert the section 6.3 round-trip law fields match exactly."""
    assert a.instructions == b.instructions
    assert a.labels == b.labels
    assert (a.n_qubits, a.n_shadow, a.n_gpr) == (
        b.n_qubits, b.n_shadow, b.n_gpr)
    assert a.stats == b.stats
    assert a.entry == b.entry == 0
    assert (a.isa_name, a.isa_version) == (b.isa_name, b.isa_version)


# ---------------------------------------------------------------------------
# Valid programs assemble (section 6.2 metadata correctness)
# ---------------------------------------------------------------------------


class TestAssembleValid:
    """Valid programs assemble with correct QOBJ metadata."""

    def test_bell_uncorrected_matches_design_doc_example(self) -> None:
        """Section 6.2's worked example values, verbatim."""
        qobj = qas.assemble(qcpu.BELL_UNCORRECTED_ASM)
        assert (qobj.isa_name, qobj.isa_version) == ("QISA-K", "0.1")
        assert (qobj.n_qubits, qobj.n_shadow, qobj.n_gpr) == (2, 2, 0)
        assert qobj.entry == 0
        assert qobj.labels == {}
        assert qobj.stats == {
            "gate_counts": {"RESET": 2, "H": 1, "CNOT": 1, "MEASURE": 2},
            "two_qubit_gate_count": 1,
            "measure_count": 2,
            "qwait_cycles": 0,
            "instruction_count": 6,
        }
        assert qobj.source_sha256 == hashlib.sha256(
            qcpu.BELL_UNCORRECTED_ASM.encode("utf-8")).hexdigest()
        first = qobj.instructions[0]
        assert (first.opcode, first.operands) == ("RESET", (0,))
        assert first.line_no == 2 and first.source == "RESET   q0"

    def test_hello_quantum(self) -> None:
        qobj = qas.assemble(qcpu.HELLO_QUANTUM_ASM)
        assert (qobj.n_qubits, qobj.n_shadow, qobj.n_gpr) == (1, 1, 0)
        assert qobj.stats["gate_counts"] == {
            "RESET": 1, "X": 1, "MEASURE": 1}
        assert qobj.stats["instruction_count"] == 3
        assert qobj.stats["two_qubit_gate_count"] == 0

    def test_bell_feedforward_statics(self) -> None:
        """Static stats count the BRN-skippable X; qwait_cycles sums."""
        qobj = qas.assemble(qcpu.BELL_FEEDFORWARD_ASM)
        assert (qobj.n_qubits, qobj.n_shadow, qobj.n_gpr) == (2, 2, 2)
        assert qobj.labels == {".skip": 9}
        assert qobj.stats["instruction_count"] == 10
        assert qobj.stats["qwait_cycles"] == 12
        assert qobj.stats["gate_counts"]["X"] == 1  # static, not runtime
        assert qobj.stats["two_qubit_gate_count"] == 1
        assert qobj.stats["measure_count"] == 2

    def test_empty_program_assembles(self) -> None:
        qobj = qas.assemble(CANONICAL_SOURCES["empty"])
        assert qobj.instructions == ()
        assert (qobj.n_qubits, qobj.n_shadow, qobj.n_gpr) == (0, 0, 0)
        assert qobj.stats["instruction_count"] == 0

    def test_assemble_file(self, tmp_path: Path) -> None:
        src = tmp_path / "bell.qs"
        src.write_text(qcpu.BELL_UNCORRECTED_ASM, encoding="utf-8")
        assert_round_trip_equal(
            qas.assemble_file(src), qas.assemble(qcpu.BELL_UNCORRECTED_ASM))

    def test_qubit_indices_are_lease_relative(self) -> None:
        """q5 alone implies a 6-qubit minimum -- valid at assemble time;
        the lease-relative check re-runs at qexec (section 6.3)."""
        qobj = qas.assemble("H q5\n")
        assert qobj.n_qubits == 6


# ---------------------------------------------------------------------------
# Every QISA opcode assembles + disassembles
# ---------------------------------------------------------------------------

_KIND_TOKENS = {"shadow": "c0", "gpr": "r0", "angle": "0.5", "imm": "7",
                "label": ".end"}


def _single_opcode_source(opcode: str, isa: qcpu.ISA) -> str:
    """Build a minimal valid program containing ``opcode``."""
    tokens: list[str] = []
    next_qubit = 0
    needs_label = False
    for spec in isa[opcode].operands:
        if spec.kind == "qubit":
            tokens.append(f"q{next_qubit}")
            next_qubit += 1
        else:
            tokens.append(_KIND_TOKENS[spec.kind])
            needs_label = needs_label or spec.kind == "label"
    text = f"{opcode} " + ", ".join(tokens) + "\n"
    if needs_label:
        text += ".end:\n"
    return text


class TestEveryOpcode:
    """Every opcode in QISA-v0.1.yaml assembles and round-trips."""

    @pytest.mark.parametrize(
        "opcode", sorted(qas._default_isa().instructions))
    def test_opcode_assembles_and_round_trips(self, opcode: str) -> None:
        source = _single_opcode_source(opcode, qas._default_isa())
        qobj = qas.assemble(source)
        assert qobj.stats["gate_counts"].get(opcode) == 1
        assert_round_trip_equal(qas.assemble(qdis.disassemble(qobj)), qobj)

    def test_all_opcodes_program_covers_isa(self) -> None:
        qobj = qas.assemble(ALL_OPCODES_ASM)
        assert set(qobj.stats["gate_counts"]) == set(
            qas._default_isa().instructions)


# ---------------------------------------------------------------------------
# Round-trip property (section 6.3, binding)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """assemble(disassemble(q)) is semantically identical to q."""

    @pytest.mark.parametrize("name", sorted(CANONICAL_SOURCES))
    def test_text_round_trip(self, name: str) -> None:
        original = qas.assemble(CANONICAL_SOURCES[name])
        reassembled = qas.assemble(qdis.disassemble(original))
        assert_round_trip_equal(reassembled, original)

    @pytest.mark.parametrize("name", sorted(CANONICAL_SOURCES))
    def test_json_round_trip_is_full_equality(self, name: str) -> None:
        """to_json -> from_json preserves the entire object, hash included."""
        original = qas.assemble(CANONICAL_SOURCES[name])
        assert qas.QObj.from_json(original.to_json()) == original
        assert qas.QObj.from_json(
            original.to_json(indent=None)) == original

    def test_line_numbers_and_sources_survive(self) -> None:
        """line_no/source carry through disassembly (listing-grade output)."""
        original = qas.assemble(qcpu.BELL_FEEDFORWARD_ASM)
        reassembled = qas.assemble(qdis.disassemble(original))
        for a, b in zip(original.instructions, reassembled.instructions):
            assert (a.line_no, a.source) == (b.line_no, b.source)

    def test_trailing_label_re_emitted(self) -> None:
        text = qdis.disassemble(
            qas.assemble(CANONICAL_SOURCES["trailing-label"]))
        assert text.rstrip().endswith(".end:")

    def test_disassemble_file(self, tmp_path: Path) -> None:
        qobj = qas.assemble(qcpu.BELL_UNCORRECTED_ASM)
        path = tmp_path / "bell.qobj.json"
        path.write_text(qobj.to_json(), encoding="utf-8")
        assert qdis.disassemble_file(path) == qdis.disassemble(qobj)


# ---------------------------------------------------------------------------
# Error classes reject with line numbers (load-time protection, section 6.3)
# ---------------------------------------------------------------------------

_BAD_SOURCES: dict[str, tuple[str, int, str]] = {
    # name: (source, expected line, message fragment)
    "unknown-opcode": ("RESET q0\nFROB q0\n", 2, "unknown opcode"),
    "bad-operand-count": ("H q0, q1\n", 1, "expects 1 operand"),
    "bad-operand-type-register": ("H c0\n", 1, "expected qubit register"),
    "bad-operand-type-angle": ("RX q0, fast\n", 1, "bad angle"),
    "bad-operand-type-imm": ("QWAIT soon\n", 1, "bad immediate"),
    "negative-immediate": ("QWAIT -3\n", 1, "negative immediate"),
    "shadow-out-of-range": ("MEASURE q0 -> c5\n", 1,
                            "shadow register c5 out of range"),
    "gpr-out-of-range": ("FMR c0 -> r9\n", 1, "GPR r9 out of range"),
    "qubit-beyond-capacity": ("H q30\n", 1, "exceeds the emulator capacity"),
    "undefined-label": ("FMR c0 -> r0\nBRN r0, .nowhere\n", 2,
                        "undefined label"),
    "duplicate-label": ("a: H q0\na: X q0\n", 2, "duplicate label"),
    "qubit-operand-duplication": ("CNOT q0, q0\n", 1,
                                  "duplicates a qubit operand"),
    "use-after-measure": ("MEASURE q0 -> c0\nH q0\n", 2,
                          "use-after-measure"),
}


class TestAssemblyErrors:
    """Each error class rejects with a line number and errno -ENOEXEC."""

    @pytest.mark.parametrize("name", sorted(_BAD_SOURCES))
    def test_rejects_with_line_number(self, name: str) -> None:
        source, line, fragment = _BAD_SOURCES[name]
        with pytest.raises(qcpu.QISAVerifierError) as excinfo:
            qas.assemble(source)
        message = str(excinfo.value)
        assert f"line {line}" in message
        assert fragment in message
        assert excinfo.value.errno == -ENOEXEC

    def test_no_new_exception_types(self) -> None:
        """The toolchain raises only qcpu.QISAVerifierError (section 8.1)."""
        with pytest.raises(qcpu.QISAVerifierError):
            qas.assemble("CNOT q0, q0\n")
        with pytest.raises(qcpu.QISAVerifierError):
            qas.QObj.from_json("not json at all")


# ---------------------------------------------------------------------------
# QOBJ envelope schema + untrusted-input validation
# ---------------------------------------------------------------------------


def _valid_envelope(source: str = qcpu.BELL_FEEDFORWARD_ASM
                    ) -> dict[str, Any]:
    """A fresh, valid envelope dict to mutate per test."""
    return json.loads(qas.assemble(source).to_json())


def _expect_envelope_reject(env: dict[str, Any], fragment: str) -> None:
    with pytest.raises(qcpu.QISAVerifierError) as excinfo:
        qas.QObj.from_json(json.dumps(env))
    assert "malformed QOBJ envelope" in str(excinfo.value)
    assert fragment in str(excinfo.value)
    assert excinfo.value.errno == -ENOEXEC


class TestQObjEnvelope:
    """Section 6.2 schema emitted exactly; bad envelopes rejected."""

    def test_envelope_schema(self) -> None:
        env = _valid_envelope(qcpu.BELL_UNCORRECTED_ASM)
        assert set(env) == set(qas._ENVELOPE_KEYS)
        assert env["format"] == "QOBJ" == qas.QOBJ_FORMAT
        assert env["format_version"] == "0.1" == qas.QOBJ_VERSION
        assert env["isa"] == {"name": "QISA-K", "version": "0.1"}
        assert env["requirements"] == {
            "n_qubits": 2, "n_shadow": 2, "n_gpr": 0}
        assert env["entry"] == 0
        assert env["instructions"][0] == {
            "opcode": "RESET", "operands": [0],
            "line_no": 2, "source": "RESET   q0"}
        assert len(env["source_sha256"]) == 64

    def test_operand_types_survive_json(self) -> None:
        """Angles stay float, registers int, labels str across JSON."""
        qobj = qas.QObj.from_json(
            qas.assemble("RX q0, 1.5\nFMR c0 -> r0\nBRN r0, .e\n.e:\n")
            .to_json())
        ops = [ins.operands for ins in qobj.instructions]
        assert ops[0] == (0, 1.5) and isinstance(ops[0][1], float)
        assert ops[1] == (0, 0)
        assert ops[2] == (0, ".e") and isinstance(ops[2][1], str)

    def test_rejects_non_json(self) -> None:
        with pytest.raises(qcpu.QISAVerifierError) as excinfo:
            qas.QObj.from_json("{nope")
        assert excinfo.value.errno == -ENOEXEC

    def test_rejects_non_object_top_level(self) -> None:
        with pytest.raises(qcpu.QISAVerifierError, match="top level"):
            qas.QObj.from_json("[1, 2]")

    def test_rejects_missing_key(self) -> None:
        env = _valid_envelope()
        del env["stats"]
        _expect_envelope_reject(env, "missing key")

    def test_rejects_wrong_format_and_version(self) -> None:
        env = _valid_envelope()
        env["format"] = "ELF"
        _expect_envelope_reject(env, "format")
        env = _valid_envelope()
        env["format_version"] = "9.9"
        _expect_envelope_reject(env, "format_version")

    def test_rejects_wrong_isa(self) -> None:
        env = _valid_envelope()
        env["isa"] = {"name": "x86", "version": "0.1"}
        _expect_envelope_reject(env, "isa block")

    def test_rejects_nonzero_entry(self) -> None:
        env = _valid_envelope()
        env["entry"] = 3
        _expect_envelope_reject(env, "entry")

    def test_rejects_unknown_opcode_inside(self) -> None:
        env = _valid_envelope()
        env["instructions"][0]["opcode"] = "FROB"
        _expect_envelope_reject(env, "unknown opcode")

    def test_rejects_bad_operand_count(self) -> None:
        env = _valid_envelope()
        env["instructions"][0]["operands"] = [0, 1]
        _expect_envelope_reject(env, "operand")

    def test_rejects_bad_operand_type(self) -> None:
        env = _valid_envelope()
        env["instructions"][0]["operands"] = ["q0"]
        _expect_envelope_reject(env, "must be an integer")

    def test_rejects_negative_operand(self) -> None:
        env = _valid_envelope()
        env["instructions"][0]["operands"] = [-1]
        _expect_envelope_reject(env, "negative")

    def test_rejects_non_increasing_line_no(self) -> None:
        env = _valid_envelope()
        env["instructions"][1]["line_no"] = (
            env["instructions"][0]["line_no"])
        _expect_envelope_reject(env, "line_no")

    def test_rejects_label_out_of_range(self) -> None:
        env = _valid_envelope()
        env["labels"] = {".skip": 99}
        _expect_envelope_reject(env, "out of range")

    def test_rejects_brn_to_missing_label(self) -> None:
        env = _valid_envelope()  # feed-forward program has a BRN
        env["labels"] = {}
        _expect_envelope_reject(env, "undefined label")

    def test_rejects_tampered_requirements(self) -> None:
        env = _valid_envelope()
        env["requirements"]["n_qubits"] += 1
        _expect_envelope_reject(env, "requirements")

    def test_rejects_tampered_stats(self) -> None:
        env = _valid_envelope()
        env["stats"]["measure_count"] += 1
        _expect_envelope_reject(env, "stats")

    def test_rejects_bad_hash(self) -> None:
        env = _valid_envelope()
        env["source_sha256"] = "xyz"
        _expect_envelope_reject(env, "source_sha256")

    def test_rejects_verifier_violation_in_envelope(self) -> None:
        """Hand-crafted use-after-measure object: untrusted-input defense
        in depth (an object file is untrusted, exactly as ELF is)."""
        env = {
            "format": "QOBJ", "format_version": "0.1",
            "isa": {"name": "QISA-K", "version": "0.1"},
            "requirements": {"n_qubits": 1, "n_shadow": 1, "n_gpr": 0},
            "entry": 0,
            "instructions": [
                {"opcode": "MEASURE", "operands": [0, 0],
                 "line_no": 1, "source": "MEASURE q0 -> c0"},
                {"opcode": "H", "operands": [0],
                 "line_no": 2, "source": "H q0"},
            ],
            "labels": {},
            "stats": {
                "gate_counts": {"MEASURE": 1, "H": 1},
                "two_qubit_gate_count": 0, "measure_count": 1,
                "qwait_cycles": 0, "instruction_count": 2,
            },
            "source_sha256": "0" * 64,
        }
        with pytest.raises(qcpu.QISAVerifierError,
                           match="use-after-measure") as excinfo:
            qas.QObj.from_json(json.dumps(env))
        assert excinfo.value.errno == -ENOEXEC


# ---------------------------------------------------------------------------
# CLI behavior (sections 8.1-8.2)
# ---------------------------------------------------------------------------


class TestCLI:
    """qas.py / qdis.py command-line round trip and exit codes."""

    def test_qas_writes_object_file(self, tmp_path: Path) -> None:
        src = tmp_path / "bell.qs"
        out = tmp_path / "bell.qobj.json"
        src.write_text(qcpu.BELL_UNCORRECTED_ASM, encoding="utf-8")
        assert qas.main([str(src), "-o", str(out)]) == 0
        loaded = qas.QObj.from_json(out.read_text(encoding="utf-8"))
        assert loaded == qas.assemble(qcpu.BELL_UNCORRECTED_ASM)

    def test_qas_stdout_default(self, tmp_path: Path,
                                capsys: pytest.CaptureFixture[str]) -> None:
        src = tmp_path / "hello.qs"
        src.write_text(qcpu.HELLO_QUANTUM_ASM, encoding="utf-8")
        assert qas.main([str(src)]) == 0
        env = json.loads(capsys.readouterr().out)
        assert env["format"] == "QOBJ"

    def test_qas_verify_only(self, tmp_path: Path,
                             capsys: pytest.CaptureFixture[str]) -> None:
        src = tmp_path / "hello.qs"
        src.write_text(qcpu.HELLO_QUANTUM_ASM, encoding="utf-8")
        assert qas.main([str(src), "--verify-only"]) == 0
        out = capsys.readouterr().out
        assert "OK" in out and "3 instruction(s)" in out
        assert list(tmp_path.iterdir()) == [src]  # nothing emitted

    def test_qas_error_exit_code_and_line(
            self, tmp_path: Path,
            capsys: pytest.CaptureFixture[str]) -> None:
        src = tmp_path / "bad.qs"
        src.write_text("CNOT q0, q0\n", encoding="utf-8")
        assert qas.main([str(src), "--verify-only"]) == 1
        err = capsys.readouterr().err
        assert "line 1" in err and f"errno {-ENOEXEC}" in err

    def test_qas_missing_file(self, tmp_path: Path,
                              capsys: pytest.CaptureFixture[str]) -> None:
        assert qas.main([str(tmp_path / "absent.qs")]) == 1
        assert "qas:" in capsys.readouterr().err

    def test_qdis_round_trip_via_cli(
            self, tmp_path: Path,
            capsys: pytest.CaptureFixture[str]) -> None:
        src = tmp_path / "ff.qs"
        obj = tmp_path / "ff.qobj.json"
        src.write_text(qcpu.BELL_FEEDFORWARD_ASM, encoding="utf-8")
        assert qas.main([str(src), "-o", str(obj)]) == 0
        assert qdis.main([str(obj)]) == 0
        listing = capsys.readouterr().out
        assert_round_trip_equal(
            qas.assemble(listing), qas.assemble(qcpu.BELL_FEEDFORWARD_ASM))

    def test_qdis_output_file(self, tmp_path: Path) -> None:
        obj = tmp_path / "bell.qobj.json"
        out = tmp_path / "bell.dis.qs"
        obj.write_text(qas.assemble(qcpu.BELL_UNCORRECTED_ASM).to_json(),
                       encoding="utf-8")
        assert qdis.main([str(obj), "-o", str(out)]) == 0
        assert_round_trip_equal(
            qas.assemble(out.read_text(encoding="utf-8")),
            qas.assemble(qcpu.BELL_UNCORRECTED_ASM))

    def test_qdis_rejects_bad_envelope(
            self, tmp_path: Path,
            capsys: pytest.CaptureFixture[str]) -> None:
        bad = tmp_path / "bad.qobj.json"
        bad.write_text('{"format": "ELF"}', encoding="utf-8")
        assert qdis.main([str(bad)]) == 1
        assert "qdis:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Toolchain output drives the emulator (and package surface)
# ---------------------------------------------------------------------------


class TestEmulatorIntegration:
    """QObj.to_program() is directly executable by qcpu.QCPU."""

    def test_bell_correlations_from_object(self) -> None:
        """The classic check: uncorrected Bell pairs satisfy c0 == c1 in
        every shot (entangled-state correlation, [Proven] quantum
        mechanics; here reproduced by the statevector emulator)."""
        program = qas.assemble(qcpu.BELL_UNCORRECTED_ASM).to_program()
        cpu = qcpu.QCPU(n_qubits=2, seed=7)
        snaps = cpu.run_shots(program, 128)
        assert all(s["c0"] == s["c1"] for s in snaps)

    def test_hello_quantum_from_round_tripped_object(self) -> None:
        qobj = qas.assemble(qcpu.HELLO_QUANTUM_ASM)
        rebuilt = qas.assemble(qdis.disassemble(qobj))
        cpu = qcpu.QCPU(n_qubits=1, seed=1)
        assert all(s["c0"] == 1
                   for s in cpu.run_shots(rebuilt.to_program(), 32))

    def test_package_exports_share_module_identity(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import toolchain
        assert toolchain.assemble is qas.assemble
        assert toolchain.disassemble is qdis.disassemble
        assert toolchain.QObj is qas.QObj
        assert toolchain.QOBJ_FORMAT == "QOBJ"
        assert toolchain.QOBJ_VERSION == "0.1"

    def test_fallback_isa_when_pyyaml_absent(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """qcpu.ISA's vendored fallback table keeps the toolchain working
        without PyYAML (design-doc ground rule: numpy/pyyaml-only runtime,
        yaml optional)."""
        monkeypatch.setitem(sys.modules, "yaml", None)  # import -> error
        isa = qcpu.ISA()
        assert not isa.loaded_from_yaml
        qobj = qas.assemble(qcpu.BELL_UNCORRECTED_ASM, isa=isa)
        assert qobj.stats["instruction_count"] == 6
        assert_round_trip_equal(
            qas.assemble(qdis.disassemble(qobj)), qobj)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
