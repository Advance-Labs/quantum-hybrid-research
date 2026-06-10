# QML-Accelerator

Theoretical analysis and simulation scaffolding for quantum-accelerated LLM training — proving (theoretically) where quantum circuits can outperform classical GPU/TPU training.

| Directory | Contents |
|-----------|----------|
| [`theory/`](theory/) | Formal speedup arguments and complexity proofs |
| [`simulations/`](simulations/) | PyTorch classical baseline + PennyLane quantum circuit equivalents |
| [`benchmarks/`](benchmarks/) | Complexity analysis and crossover-point plotting |

See [`docs/research/01-qml-accelerator.md`](../docs/research/01-qml-accelerator.md) for the research foundation and [`docs/workflows/01-qml-workflow.md`](../docs/workflows/01-qml-workflow.md) for the engineering workflow.
