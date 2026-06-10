# QuantumLinux

Theoretical port of the Linux kernel to a quantum computing architecture — a designed-from-scratch Quantum ISA (QISA), a Python quantum CPU emulator, and an analysis of every kernel subsystem's portability.

| Directory | Contents |
|-----------|----------|
| [`isa-spec/`](isa-spec/) | QISA v0.1 — machine-readable quantum instruction set definition |
| [`emulator/`](emulator/) | Python quantum CPU emulator + test suite |
| [`kernel-patches/`](kernel-patches/) | `arch/quantum/` adaptation notes and quantum syscall headers |

See [`docs/research/02-quantum-linux.md`](../docs/research/02-quantum-linux.md) for the research foundation and [`docs/workflows/02-linux-workflow.md`](../docs/workflows/02-linux-workflow.md) for the engineering workflow.
