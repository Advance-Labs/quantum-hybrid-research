# quantum-hybrid-research

> Theoretical research and implementation scaffolding at the quantum/classical intersection: quantum-accelerated LLM training, Linux as the control plane for quantum hardware, and a hybrid classical/quantum motherboard reference architecture.

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Status: Theoretical Research](https://img.shields.io/badge/Status-theoretical_research-orange.svg)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)
![Emulator Tests](https://img.shields.io/badge/quantum--linux_emulator-72%2F72_tests_passing-brightgreen.svg)

The QuantumLinux statevector emulator ships with a 72-test pytest suite (`quantum-linux/emulator/test_hello_quantum.py`) that passes in full; all other code artifacts compile and run as reference models.

## Overview

This repository is an [Advance Labs](https://advancelabs.dev) research initiative asking three concrete questions about where quantum and classical computing meet:

1. **Can quantum subroutines accelerate LLM training?** (QML-Accelerator)
2. **Can the Linux kernel be ported to quantum hardware?** (QuantumLinux)
3. **Can a QPU live on a motherboard next to a CPU and GPU?** (HybridBoard)

The honest framing matters: this is **theoretical research plus implementation scaffolding**, not a product. The research documents reach sober conclusions and the code exists to *measure honestly*, not to demonstrate an advantage that does not exist:

- **QML-Accelerator** finds the asymptotic speedup arguments are real but narrow, input/output bottlenecks are severe, the quantum clock-speed deficit is roughly eight to ten orders of magnitude, and **no credible path delivers practical LLM-training acceleration before the mid-2030s. Readiness score: 2/10.**
- **QuantumLinux** concludes a literal port is **impossible in principle** — a corollary of the [Proven] no-cloning theorem and measurement postulate (`fork()`, copy-on-write, and preemption have no physical realization for quantum state). Linux as the classical *control plane* for a QPU, via a narrow `QALLOC`/`QEXEC`/`QMEASURE`/`QFREE` syscall interface, is the only viable design — and is already how every deployed quantum computer works.
- **HybridBoard** finds the binding constraint is **latency, not bandwidth** (the control loop must close well inside qubit coherence times); for superconducting QPUs a "motherboard" is a category error — the system is a rack-and-cryostat installation — and no consumer market for such a board exists today.

Why explore it anyway: the hybrid classical/quantum split is the asymptotically correct division of labor, not a temporary compromise. Working out the workload theory, the OS interface, and the hardware platform *now* — with every claim tagged by its evidence level — is cheap, and produces a reusable map of exactly where the bottlenecks are.

## Architecture

The three projects form one vertical stack — workload, operating system, hardware:

```
┌────────────────────────────────────────────────────────────────────┐
│  QML-ACCELERATOR                                  (the workload)   │
│  Quantum subroutines for LLM training: amplitude-estimation       │
│  gradients, quantum attention, hybrid training loop, crossover     │
│  analysis.  PyTorch classical baseline + PennyLane circuits.       │
│  → qml-accelerator/                                                │
└───────────────────────────────┬────────────────────────────────────┘
                                │ hybrid jobs: classical tensors +
                                │ quantum circuit blobs
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│  QUANTUMLINUX                                     (the OS layer)   │
│  Linux as the classical control plane for a QPU.                   │
│  QISA-K instruction set · qsyscalls (QALLOC/QEXEC/QMEASURE/QFREE)  │
│  · statevector emulator (72 tests) · kernel subsystem audit.       │
│  → quantum-linux/                                                  │
└───────────────────────────────┬────────────────────────────────────┘
                                │ compiled QISA circuits + control
                                │ words over the QCX bus (≤2 µs loop)
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│  HYBRIDBOARD                              (the hardware platform)  │
│   ┌─────────┐ ┌─────────┐ ┌─────────┐          ┌────────────────┐  │
│   │   CPU   │ │   GPU   │ │   NPU   │   QCX    │ QPU + pulse    │  │
│   │ chiplets│ │  HBM3e  │ │  tile   │◄────────►│ control        │  │
│   └─────────┘ └─────────┘ └─────────┘   bus    │ (+ cryostat)   │  │
│   shared classical address space               └────────────────┘  │
│   (quantum registers are never memory-mapped — no-cloning)         │
│  QCX protocol · ACPI QDEV firmware · hybrid scheduler · power      │
│  model.  → hybrid-board/                                           │
└────────────────────────────────────────────────────────────────────┘
```

Measurement results (classical bits) flow back up the same path: QPU → ring buffers on the QCX host endpoint → `QMEASURE` return values → the training loop's gradient estimate.

## Table of Contents

| Project | Code & README | Research document | Engineering workflow |
|---|---|---|---|
| **QML-Accelerator** — quantum speedup analysis for LLM training | [`qml-accelerator/`](qml-accelerator/README.md) | [`docs/research/01-qml-accelerator.md`](docs/research/01-qml-accelerator.md) | [`docs/workflows/01-qml-workflow.md`](docs/workflows/01-qml-workflow.md) |
| **QuantumLinux** — Linux-on-quantum feasibility, QISA, emulator | [`quantum-linux/`](quantum-linux/README.md) | [`docs/research/02-quantum-linux.md`](docs/research/02-quantum-linux.md) | [`docs/workflows/02-linux-workflow.md`](docs/workflows/02-linux-workflow.md) |
| **HybridBoard** — classical/quantum motherboard architecture | [`hybrid-board/`](hybrid-board/README.md) | [`docs/research/03-hybrid-board.md`](docs/research/03-hybrid-board.md) | [`docs/workflows/03-hybridboard-workflow.md`](docs/workflows/03-hybridboard-workflow.md) |

Recommended reading order per project: research document → workflow → code.

## Repository Structure

```
quantum-hybrid-research/
├── README.md                              # this file
├── LICENSE                                # MIT, Advance Labs Inc.
├── docs/
│   ├── research/
│   │   ├── 01-qml-accelerator.md          # QML theory survey; readiness 2/10 verdict
│   │   ├── 02-quantum-linux.md            # kernel-port feasibility; hybrid control-plane verdict
│   │   └── 03-hybrid-board.md             # board feasibility; latency/power/TRL analysis
│   └── workflows/
│       ├── 01-qml-workflow.md             # 5-stage build plan for qml-accelerator/
│       ├── 02-linux-workflow.md           # 5-stage build plan for quantum-linux/
│       └── 03-hybridboard-workflow.md     # 5-stage build plan for hybrid-board/
├── qml-accelerator/
│   ├── README.md
│   ├── requirements.txt                   # torch, pennylane(+lightning), numpy, scipy, matplotlib, pytest
│   ├── theory/
│   │   └── speedup_proof.md               # O(√N) gradient-estimation sketch, assumptions stated
│   ├── simulations/
│   │   ├── classical_transformer.py       # instrumented PyTorch baseline (Stage 1)
│   │   ├── quantum_attention.py           # PennyLane attention-circuit equivalents (Stage 2)
│   │   └── hybrid_training_loop.py        # classical forward → quantum gradient → update (Stage 3)
│   └── benchmarks/
│       └── complexity_analysis.py         # cost tables + crossover plots (Stage 4)
├── quantum-linux/
│   ├── README.md
│   ├── requirements.txt                   # numpy, pytest, PyYAML, qiskit
│   ├── isa-spec/
│   │   └── QISA-v0.1.yaml                 # machine-readable QISA-K instruction set
│   ├── emulator/
│   │   ├── qcpu.py                        # numpy statevector quantum CPU emulator
│   │   └── test_hello_quantum.py          # 72-test pytest suite (passing)
│   └── kernel-patches/
│       ├── arch-quantum-notes.md          # per-subsystem portability audit notes
│       └── qsyscall.h                     # QALLOC/QEXEC/QMEASURE/QFREE C11 header
└── hybrid-board/
    ├── README.md
    ├── requirements.txt                   # numpy, matplotlib, jupyter
    ├── architecture/
    │   ├── HYBRIDBOARD-ARCH-v0.1.md       # board block diagram + component selection
    │   └── QCX-PROTOCOL-v0.1.md           # Quantum Compute Express bus spec (CXL 3.1-derived)
    ├── firmware/
    │   ├── QPUINIT.md                     # UEFI QPU initialization sequence
    │   └── ACPI-QDEV.md                   # ACPI quantum device enumeration object
    └── scheduler/
        ├── quantum_scheduler.c            # hybrid workload-routing reference model (C11)
        └── power_model.py                 # thermal/power model of research doc §6
```

## Getting Started

All Python code targets **Python ≥ 3.11**. Each sub-project is self-contained.

### qml-accelerator

```bash
cd qml-accelerator
pip install -r requirements.txt

# Full dependencies installed — run the classical baseline:
python simulations/classical_transformer.py

# No heavy deps needed for these two modes:
python benchmarks/complexity_analysis.py --table-only   # cost tables + crossover findings, no matplotlib
python simulations/hybrid_training_loop.py --dry-run    # prints the execution plan, no torch/pennylane
```

### quantum-linux

```bash
cd quantum-linux
pip install numpy pyyaml pytest        # or: pip install -r requirements.txt

pytest emulator/test_hello_quantum.py  # 72 tests — Bell pairs, feed-forward, QISA-K semantics
```

### hybrid-board

```bash
cd hybrid-board

# Hybrid scheduler reference model (C11, userspace only):
cc -std=c11 -Wall -Wextra -Werror -DQSCHED_DEMO \
   -o /tmp/qsched scheduler/quantum_scheduler.c && /tmp/qsched

# Thermal/power model (Markdown tables, no matplotlib needed):
python scheduler/power_model.py --table-only
```

## Technology Stack

| Technology | Used for |
|---|---|
| **Python 3.11+** | All simulations, the statevector emulator, benchmarks, and power models |
| **PyTorch** (≥ 2.3) | Instrumented classical transformer baseline, autograd, `torch.profiler` timing |
| **PennyLane** (≥ 0.38, + `pennylane-lightning`) | Quantum circuit construction, parameter-shift gradients, PyTorch interface |
| **Qiskit** (≥ 1.0) | Cross-validation experiments against the QISA-K circuits (the emulator itself is numpy-only) |
| **NumPy** (≥ 1.26) | `complex128` statevector simulation (~24-qubit laptop ceiling) and shared numerics |
| **C (C11)** | `quantum_scheduler.c` workload-routing reference model; `qsyscall.h` syscall header (compile-checked, no kernel build) |
| **YAML** (PyYAML ≥ 6.0) | `QISA-v0.1.yaml` — the machine-readable QISA-K instruction-set specification |

## Research Methodology

Every claim in every document in this repository carries one of four epistemic tags:

- **[Proven]** — mathematically proven
- **[Demonstrated]** — experimentally shown on real hardware
- **[Theoretical]** — rigorous but unproven in practice
- **[Speculative]** — extrapolation or conjecture

Untagged sentences are context, not claims. Tags are never silently promoted when material moves between documents, and citations (arXiv papers, vendor roadmaps, hardware specs) were web-verified against the June 2026 state of the field at the time of writing. Anything tagged [Speculative] that appears in code (e.g. qRAM assumptions) is modeled as a labeled assumption with a tunable constant — never treated as free.

## Contributing

Issues and pull requests are welcome.

- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, ...).
- Any factual claim added to docs must carry one of the four tags above; do not promote a tag.
- Citations must be verifiable (arXiv ID, DOI, or stable vendor URL).
- Code must pass the relevant per-project checks before submission:
  - `pytest quantum-linux/emulator/test_hello_quantum.py`
  - `python -m py_compile` on any touched Python file
  - `cc -std=c11 -fsyntax-only hybrid-board/scheduler/quantum_scheduler.c` (and any touched C file)

## License

[MIT](LICENSE) © 2026 Advance Labs Inc.

---

<p align="center">
  Built by <a href="https://advancelabs.dev"><b>Advance Labs Inc.</b></a> — a Canadian software studio. We design, build, and ship our own software products.<br>
  <a href="https://advancelabs.dev">advancelabs.dev</a> · <a href="https://github.com/Advance-Labs">github.com/Advance-Labs</a>
</p>
