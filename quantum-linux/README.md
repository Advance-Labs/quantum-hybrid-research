# QuantumLinux

Theoretical port of the Linux kernel to a quantum computing architecture — a designed-from-scratch Quantum ISA (QISA), a Python quantum CPU emulator, and an analysis of every kernel subsystem's portability.

| Directory | Contents |
|-----------|----------|
| [`isa-spec/`](isa-spec/) | QISA v0.1 — machine-readable quantum instruction set definition |
| [`emulator/`](emulator/) | Python quantum CPU emulator + test suites (`test_hello_quantum.py`, `test_kernel_init.py`) |
| [`qos/`](qos/) | QLOS v0.1 — user-space runtime (`qsyscalls.py`), lease-based scheduler (`scheduler.py`), and the binding design doc [`QLOS-DESIGN-v0.1.md`](qos/QLOS-DESIGN-v0.1.md) |
| [`toolchain/`](toolchain/) | `qas.py` assembler (QISA-K `.qs` text → QOBJ v0.1 JSON) and `qdis.py` disassembler (round-trip safe) |
| [`examples/`](examples/) | QISA-K example programs (`bell.qs`, `hello_quantum.qs`, `teleport.qs`) + `qrun.py` dev-loop driver |
| [`kernel-patches/`](kernel-patches/) | `arch/quantum/` adaptation notes, quantum syscall headers, and the kernel-subsystem [`compatibility-matrix.md`](kernel-patches/compatibility-matrix.md) |

See [`docs/research/02-quantum-linux.md`](../docs/research/02-quantum-linux.md) for the research foundation and [`docs/workflows/02-linux-workflow.md`](../docs/workflows/02-linux-workflow.md) for the engineering workflow.

## QLOS v0.1 — the normalized dev loop

QLOS (the QuantumLinux OS runtime — never "QOS", to avoid collision with the QOS paper the research doc cites) is a **user-space realization** of the control-plane architecture: a classical runtime that leases qubits, verifies and schedules circuits, and returns only classical measurement shadows via the four-call `QALLOC`/`QEXEC`/`QMEASURE`/`QFREE` discipline of [`kernel-patches/qsyscall.h`](kernel-patches/qsyscall.h). Nothing in QLOS runs *on* qubits — the point is that quantum hardware gets a normalized, classical-style development process mirroring **edit → cc → exec → gdb**:

```bash
cd quantum-linux
pip install numpy pyyaml pytest        # or: pip install -r requirements.txt

# edit — write QISA-K assembly (see examples/*.qs)
$EDITOR examples/bell.qs

# cc — assemble .qs → QOBJ v0.1 JSON, validated against isa-spec/QISA-v0.1.yaml
python toolchain/qas.py examples/bell.qs -o /tmp/bell.qobj.json

# exec — submit through the QLOS runtime (qalloc/qexec/qmeasure/qfree);
# prints measured counts (~50/50 between 00 and 11) + gate stats
python examples/qrun.py examples/bell.qs --shots 1024

# gdb — single-step one debug shot with per-instruction statevector
# amplitudes (emulation-only; physically impossible on hardware)
python examples/qrun.py examples/bell.qs --trace --seed 42

# objdump — disassemble the QOBJ back to canonical .qs (round-trip safe)
python toolchain/qdis.py /tmp/bell.qobj.json
```

The full stack carries a 228-test pytest suite (`pytest quantum-linux/` from the repo root, run in CI by [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)):

```bash
pytest emulator/test_hello_quantum.py   # 72 — emulator: Bell pairs, feed-forward, QISA-K semantics
pytest qos/test_qos.py                  # 55 — runtime + scheduler: syscall/errno contract, leases, admission
pytest toolchain/test_toolchain.py      # 85 — assembler/disassembler: validation, round-trip safety
pytest emulator/test_kernel_init.py     # 16 — Stage 5 kernel-init harness booting through QLOS
```

The binding interface contract for all of this is [`qos/QLOS-DESIGN-v0.1.md`](qos/QLOS-DESIGN-v0.1.md).
