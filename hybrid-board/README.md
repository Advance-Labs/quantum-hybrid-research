# HybridBoard

A theoretical motherboard reference architecture integrating a classical CPU/GPU chipset with a Quantum Processing Unit (QPU) over a custom Quantum Compute Express (QCX) bus.

| Directory | Contents |
|-----------|----------|
| [`architecture/`](architecture/) | Board architecture document + QCX bus protocol spec |
| [`firmware/`](firmware/) | UEFI QPU initialization and ACPI quantum device enumeration |
| [`scheduler/`](scheduler/) | Hybrid workload scheduler (C) + thermal/power simulation (Python) |

See [`docs/research/03-hybrid-board.md`](../docs/research/03-hybrid-board.md) for the research foundation and [`docs/workflows/03-hybridboard-workflow.md`](../docs/workflows/03-hybridboard-workflow.md) for the engineering workflow.
