# QML-Accelerator — Quantum Acceleration of LLM Training: Theoretical Foundations

**Project:** quantum-hybrid-research / qml-accelerator
**Status:** Research document — theoretical foundations
**Last updated:** June 2026
**Epistemic convention:** Every claim in this document carries one of four tags: **[Proven]** (mathematically proven), **[Demonstrated]** (experimentally shown on real hardware), **[Theoretical]** (rigorous but unproven in practice), **[Speculative]** (extrapolation or conjecture). Untagged sentences are context, not claims.

---

## 1. Abstract

This document surveys the theoretical foundations for accelerating large language model (LLM) training with quantum subroutines, and assesses — honestly — how far current theory and hardware are from delivering it. We review the three canonical quantum speedup primitives (Grover search, Quantum Amplitude Estimation, and the HHL linear-systems algorithm) and analyze concretely whether each applies to gradient descent and backpropagation; we cover variational quantum circuits, quantum natural gradient, and the barren plateau obstruction with its known mitigations; we examine quantum approaches to matrix multiplication through inner-product estimation and the block-encoding / quantum singular value transformation (QSVT) framework, including the state-preparation and tomography bottlenecks that dominate end-to-end cost; and we present a clearly-labeled theoretical proof sketch for an O(√N)-query gradient-estimation scheme for a transformer attention layer, stating every assumption it rests on. We then derive hardware requirements (logical qubits, gate fidelity, coherence) to outperform an NVIDIA A100 at 1B/7B/70B parameter scales, and ground a viability timeline in the web-verified June 2026 state of the IBM, Google, and IonQ roadmaps. Headline finding: the asymptotic arguments are real but narrow, the input/output bottlenecks are severe, the quantum clock-speed deficit is roughly eight to ten orders of magnitude, and no credible path delivers practical LLM-training acceleration before the mid-2030s. Readiness score: 2/10.

---

## 2. Quantum Speedup Theory

Three primitives account for nearly all proposed quantum speedups in machine learning. For each we state the proven complexity, its preconditions, and — critically — whether it maps onto gradient descent and backpropagation.

### 2.0 What "Speedup" Means Here (and What It Does Not)

Quantum complexity results are almost always stated in the *query model*: cost is counted in calls to an oracle U_f, not in wall-clock seconds. Three translation losses occur between a query-model theorem and a training-loop speedup, and each must be accounted for explicitly:

1. **Oracle synthesis cost.** The oracle must be compiled into gates. For ML workloads the "oracle" is a forward (or forward+backward) pass over a model — its reversible compilation typically inflates depth and width by polylogarithmic factors and constants of 10²–10⁴ relative to the irreversible classical circuit. **[Theoretical]**
2. **Input/output cost.** Loading classical data into amplitudes costs Ω(N) gates without qRAM; reading an N-dimensional answer out costs Ω(N/ε²) samples by tomography lower bounds. Speedups survive only when both ends stay logarithmic. **[Proven]**
3. **Clock rate.** A fault-tolerant logical gate today is projected at 10⁴–10⁶ ops/s versus ~10¹⁴ FLOP/s sustained on a single A100 [23][24]. A quadratic query advantage of √N must first repay a ~10⁸–10¹⁰× constant before any crossover. **[Demonstrated]** ~1 µs physical cycle times [24]; **[Theoretical]** logical-rate extrapolation; **[Proven]** consequence.

Throughout this document, "O(·)" refers to query or gate complexity as stated at each claim site; wall-clock implications are treated separately in Section 7.

### 2.1 Grover's Algorithm — O(√N) Unstructured Search

**Statement.** Given oracle access to a function f : {0,...,N−1} → {0,1} with a marked element, Grover's algorithm finds a marked element with O(√N) oracle queries, versus Θ(N) classically; this query complexity is optimal for quantum computers. **[Proven]** (Grover 1996, arXiv:quant-ph/9605043 [1]). Small instances have been executed on real devices, but never at a scale where the quadratic advantage beats classical hardware in wall-clock time. **[Demonstrated]** only at toy scale.

**Application to gradient descent / backpropagation.** Backpropagation is not an unstructured search: the gradient ∇L(θ) is computed by a *structured* reverse-mode sweep that obtains all d partial derivatives in O(1) times the cost of a forward pass — already optimal up to constants. Grover offers no speedup for that computation. **[Proven]** in the sense that Grover's speedup applies only to query problems with an oracle structure backprop does not have. Where Grover-type amplification *can* plausibly enter training pipelines:

- **Data/example selection:** finding a training example satisfying a predicate (e.g., loss above threshold) among N examples in O(√N) oracle calls — but each oracle call must coherently evaluate the model, which costs a full forward pass inside a reversible circuit. **[Theoretical]**
- **Hyperparameter / discrete architecture search:** searching N discrete configurations in O(√N) evaluations, with the same caveat that each evaluation is a full (coherent) training run — almost always prohibitive. **[Speculative]**

### 2.2 Quantum Amplitude Estimation (QAE) — Quadratic Monte-Carlo Speedup

**Statement.** Given a unitary A preparing a state with success amplitude √a, QAE estimates a to additive error ε using O(1/ε) applications of A and A†, versus Θ(1/ε²) samples for classical Monte Carlo estimation. **[Proven]** (Brassard, Høyer, Mosca, Tapp 2000, arXiv:quant-ph/0005055 [2]).

**Application to gradient descent / backpropagation.** This is the most defensible entry point for quantum training speedups. A minibatch gradient component is an empirical mean

  g_j = (1/N) Σ_{i=1}^{N} ∂ℓ(x_i; θ)/∂θ_j ,

i.e., exactly the kind of mean QAE accelerates. If per-example gradients can be evaluated *coherently* (the per-example forward+backward pass compiled as a reversible quantum circuit) and amplitude-encoded, QAE estimates g_j to additive error ε with O(1/ε) coherent evaluations instead of O(1/ε²) classical samples. **[Theoretical]** The catch: (i) the estimate is per-component, so a d-parameter model naively pays a factor d; (ii) the coherent evaluation circuit is enormously deeper than the classical forward pass; (iii) classical practice does not demand high-precision gradients — SGD thrives on noisy O(1)-sample estimates, which blunts the value of precision speedups. Section 7 quantifies this.

### 2.3 HHL — Quantum Linear Systems in O(log N · s² κ² / ε)

**Statement.** Given an s-sparse, N×N Hermitian matrix A with condition number κ, and a quantum state |b⟩, the HHL algorithm prepares a state proportional to A⁻¹|b⟩ in time Õ(log(N) · s² κ² / ε), versus Ω(N) for any classical algorithm that merely writes the answer down. **[Proven]** as a quantum-state-output algorithm (Harrow, Hassidim, Lloyd 2009, Phys. Rev. Lett. 103, 150502, arXiv:0811.3171 [3]).

**The famous caveats** (Aaronson, "Read the fine print," Nature Physics 11, 291–293, 2015 [4]) — every one must hold or the exponential advantage evaporates:

1. **State preparation:** |b⟩ must be preparable in O(polylog N) time. For arbitrary classical data this requires qRAM (Section 6) or special structure; loading N generic amplitudes costs Ω(N) without it. **[Proven]**
2. **Readout:** the output is a quantum state |x⟩, not the vector x. Reading all N entries requires Ω(N) tomography samples — the algorithm only helps if you need a *global property* ⟨x|M|x⟩ of the solution. **[Proven]**
3. **Condition number:** runtime scales as κ²; ill-conditioned systems (common for neural-network curvature matrices, whose spectra are notoriously broad) lose the advantage. **[Proven]**
4. **Sparsity / block-encoding access:** A must be sparse or efficiently block-encodable. Dense, unstructured weight matrices are not. **[Proven]**
5. **Dequantization:** for low-rank matrices with sampling-and-query access, quantum-inspired classical algorithms achieve polylogarithmic dependence on dimension too, eliminating claimed exponential separations (Tang 2019, STOC, arXiv:1807.04271 [5]). **[Proven]**

**Application to gradient descent / backpropagation.** HHL targets *second-order* methods: a Newton step solves Hδ = −∇L with H the d×d Hessian. In principle HHL prepares |δ⟩ in Õ(log d · κ²/ε) given a block-encoding of H. In practice all five caveats bind at once: H is dense, implicit, ill-conditioned, must be re-block-encoded every step, and the parameter update needs the *classical vector* δ — an Ω(d) readout that erases the log d advantage. **[Theoretical]**, and after caveats, **[Speculative]** that any end-to-end second-order training advantage survives.

### Table 1 — Quantum speedup primitives vs. training-relevant classical baselines

| Primitive | Quantum complexity | Classical baseline | Speedup | Preconditions | Status |
|---|---|---|---|---|---|
| Grover search [1] | O(√N) queries | Θ(N) queries | Quadratic | Oracle structure; coherent f evaluation | **[Proven]** (query model) |
| Amplitude estimation [2] | O(1/ε) calls | Θ(1/ε²) samples | Quadratic in precision | Coherent sampler A; per-quantity readout | **[Proven]** |
| HHL linear solver [3] | Õ(log N · s²κ²/ε) | O(N·s·κ) (CG, to state vector) | Exponential in N (state output only) | qRAM/state prep, sparse A, low κ, global-property readout | **[Proven]** with caveats [4] |
| Backprop (classical) | — | O(1)× forward-pass cost for all d derivatives | — | — | **[Proven]** optimal up to constants |

---

## 3. Quantum Neural Networks

### 3.1 Variational Quantum Circuits (VQCs)

A VQC is a parameterized unitary U(θ) = Π_ℓ U_ℓ(θ_ℓ) W_ℓ applied to an input encoding |ψ(x)⟩, with predictions read out as expectation values C(θ) = ⟨ψ(x)|U†(θ) M U(θ)|ψ(x)⟩ and θ optimized by a classical outer loop. This hybrid pattern defines essentially all near-term quantum ML (Preskill 2018, Quantum 2, 79, arXiv:1801.00862 [6]).

**Gradient access.** For gates generated by Pauli operators, the parameter-shift rule gives the exact analytic derivative from two shifted circuit evaluations:

  ∂C/∂θ_k = ½ [ C(θ_k + π/2) − C(θ_k − π/2) ]. **[Proven]**

This means a d-parameter VQC costs **O(d) circuit executions per gradient step on hardware** — each repeated O(1/ε²) shots to resolve the expectation value to precision ε. There is no hardware analogue of reverse-mode backpropagation's O(1)-sweep amortization (adjoint differentiation achieves it only on classical *simulators*). This inverts the usual economics: classical networks pay O(1) passes for all d derivatives; quantum circuits pay O(d/ε²) executions. **[Proven]** for the standard measurement model.

**Input encoding.** Angle encoding uses n qubits for n features at O(n) depth; amplitude encoding packs 2ⁿ features into n qubits but requires O(2ⁿ) gate depth in general for arbitrary data — the same input bottleneck as Section 2.0 in miniature. **[Proven]**

**Status.** VQC classifiers and small generative models are **[Demonstrated]** at the scale of tens of qubits on superconducting and trapped-ion devices; useful advantage over classical networks at equal wall-clock cost remains **[Speculative]**. Quantum attention architectures with asymptotic run-time and parameter-count advantages over classical counterparts have been formally analyzed (Cherrat et al., Quantum 8, 1265, 2024, arXiv:2209.08167 [28]) — these results are **[Theoretical]** and inherit the state-preparation assumptions of Section 4.

### 3.2 Quantum Natural Gradient (QNG)

QNG (Stokes, Izaac, Killoran, Carleo 2020, arXiv:1909.02108 [7]) preconditions the gradient with the Fubini–Study metric tensor g(θ) (the real part of the quantum geometric tensor): θ ← θ − η g⁺(θ)∇L(θ). This is the quantum analogue of classical natural gradient descent and respects the information geometry of the state manifold rather than the raw parameter space. A block-diagonal approximation of g(θ) is computable with additional circuits at O(d) overhead per layer. **[Theoretical]** with **[Demonstrated]** small-scale convergence improvements in simulation and on hardware testbeds; no proven asymptotic training advantage.

### 3.3 The Barren Plateau Problem

McClean, Boixo, Smelyanskiy, Babbush, Neven (Nature Communications 9, 4812, 2018, arXiv:1803.11173 [8]) proved that for random parameterized circuits matching the statistics of unitary 2-designs, gradients vanish exponentially in qubit count n:

  E[∂C/∂θ_k] = 0 and Var[∂C/∂θ_k] ∈ O(2⁻ⁿ). **[Proven]**

Consequently the number of measurement shots needed to resolve a gradient direction grows as Ω(2ⁿ) — random deep VQCs are untrainable at scale. Cerezo, Sone, Volkoff, Cincio, Coles (arXiv:2001.00550 [9]) sharpened this: *global* cost functions (observables acting on all qubits) exhibit barren plateaus even at shallow depth, while *local* cost functions retain polynomially vanishing (trainable) gradients provided circuit depth is O(log n). **[Proven]**

### 3.4 Mitigation Strategies

| Strategy | Mechanism | Guarantee | Key reference | Status |
|---|---|---|---|---|
| Local cost functions | Replace global observables with sums of few-qubit observables | Gradient variance vanishes only polynomially for depth O(log n) | Cerezo et al. [9] | **[Proven]** |
| Identity-block initialization | Initialize circuit as a sequence of shallow blocks evaluating to identity, limiting effective depth at step 0 | Avoids plateau at initialization (not throughout training) | Grant, Wossnig, Ostaszewski, Benedetti 2019, arXiv:1903.05076 [10] | **[Theoretical]** + **[Demonstrated]** in simulation |
| Layerwise training | Grow circuit depth incrementally; train parameter subsets | Empirically larger gradient magnitudes; ~8% lower test error in digit-classification experiments | Skolik, McClean, Mohseni, van der Smagt, Leib 2021, arXiv:2006.14904 [11] | **[Demonstrated]** in simulation |
| Parameter correlation | Tie gates spatially/temporally to shrink effective parameter dimension | Provable transition from vanishing to non-vanishing gradient variance for correlated modules | Volkoff & Coles 2021, arXiv:2005.12200 [12] | **[Proven]** for analyzed ansatz families |

An important honest note: mitigations that guarantee trainability tend to do so by restricting the circuit family toward classically-simulable regimes; whether any trainable-yet-classically-hard VQC family exists with a *learning* advantage is open. **[Speculative]** either way.

---

## 4. Quantum Advantage for Matrix Multiplication

LLM training cost is dominated by dense matrix multiplication (the QKᵀ, attention-weighted V, and MLP products). Any honest quantum-acceleration story must confront this workload directly.

### 4.0 Where the FLOPs Actually Are

For a transformer with model width d_model, sequence length L, and batch B, one layer's forward pass costs (per standard accounting): QKV projections O(B·L·d_model²), attention scores QKᵀ O(B·L²·d_model), attention-weighted values O(B·L²·d_model), output projection O(B·L·d_model²), and MLP O(B·L·d_model²) with the customary 4× expansion. The backward pass costs ≈2× the forward. Every one of these terms is a dense matmul; a quantum method that cannot beat dense matmul throughput cannot accelerate LLM training in the large. **[Proven]** accounting.

### 4.1 Classical Baselines

Naive multiplication of n×n matrices costs O(n³). Strassen's algorithm reduces this to O(n^2.807) (Strassen 1969 [13]). The best known asymptotic exponent as of 2026 is ω < 2.371339 (Alman, Duan, Vassilevska Williams, Xu, Xu, Zhou, SODA 2025, arXiv:2404.16349 [14]), improving the SODA 2024 bound of ω < 2.371552 [15]. **[Proven]** — though galactic: practical GPU kernels use the O(n³) schedule because of constants and memory hierarchy.

### 4.2 Quantum Inner-Product Estimation

Each entry of C = AB is an inner product of n-dimensional vectors. Given state-preparation unitaries for |a_i⟩ and |b_j⟩, a swap/Hadamard-test estimator yields ⟨a_i|b_j⟩-derived quantities to additive error ε in O(1/ε²) shots, improved to O(1/ε) with amplitude estimation [2]. **[Proven]** as estimation primitives. But: the output is an ε-*estimate*, not an exact entry; producing all n² entries costs O(n²/ε) total even with free state preparation, which beats no classical exact algorithm once ε must scale like the precision needed for stable training (mixed-precision training tolerates coarse error, but errors here are *statistical per-entry*, behaving like multiplicative noise on every matmul, which is much harsher than deterministic rounding). **[Theoretical]**, end-to-end advantage **[Speculative]**.

### 4.3 Block-Encoding and Quantum Singular Value Transformation (QSVT)

The modern framing (Gilyén, Su, Low, Wiebe, STOC 2019, arXiv:1806.01838 [16]) embeds a matrix A/α as the top-left block of a unitary U_A ("block-encoding," with subnormalization α). Then:

- Products: block-encodings compose — U_AB is built from one call each to U_A and U_B, with subnormalization α_A·α_B. **[Proven]**
- Applying AB to a state |ψ⟩ therefore costs O(polylog n) gates *given* efficient block-encodings, with success amplitude ‖AB|ψ⟩‖/(α_A α_B) — repetition or amplitude amplification cost O(α_A α_B / ‖AB|ψ⟩‖). **[Proven]**
- QSVT applies arbitrary degree-k polynomial transformations to singular values with k uses of the block-encoding, unifying HHL, Hamiltonian simulation, and amplitude amplification in one framework. **[Proven]**

### 4.4 The Honest Input/Output Accounting

The polylog(n) gate counts above hide two Ω(n)-to-Ω(n²) walls:

1. **Input (state preparation / block-encoding construction):** building a block-encoding of a dense, unstructured n×n matrix from classical data requires either O(n²) preprocessing into a qRAM-backed data structure (Kerenidis & Prakash 2016, arXiv:1603.08675 [17]) or O(n²) gate constructions. qRAM itself (Giovannetti, Lloyd, Maccone 2008, Phys. Rev. Lett. 100, 160501, arXiv:0708.1879 [18]) requires O(n²) physical hardware cells; a cryogenic, error-corrected qRAM at LLM scale (10⁹–10¹¹ weights) has never been demonstrated at any scale. **[Proven]** costs; hardware **[Speculative]**.
2. **Output (tomography):** extracting the classical n-dimensional (or n×n) result from the output state requires Ω(n/ε²) samples by standard tomography lower bounds; the polylog advantage survives only if the result stays quantum (feeding the next layer coherently) or only scalar properties are read out. Keeping an entire transformer forward+backward pass coherent end-to-end multiplies circuit depth catastrophically (Section 7). **[Proven]** bottleneck.
3. **Dequantization:** where data admits the sampling-and-query access that qRAM would provide, Tang-style classical algorithms often match the quantum polylog scaling up to polynomial factors in rank/condition number, collapsing the claimed separation for low-rank regimes [5]. **[Proven]**

### Table 2 — Matrix multiplication: complexity comparison (n×n dense)

| Method | Asymptotic cost | Output form | Hidden requirements | Status |
|---|---|---|---|---|
| Naive classical | O(n³) | Exact classical matrix | — | **[Proven]** |
| Strassen [13] | O(n^2.807) | Exact classical matrix | Numerical-stability care | **[Proven]** |
| Best known (laser method) [14] | O(n^2.371339) | Exact classical matrix | Galactic constants; impractical | **[Proven]** |
| GPU tensor cores (A100) | O(n³) schedule, ~3.1×10¹⁴ FLOP/s peak | Exact (to FP16/BF16) | — | **[Demonstrated]** |
| Quantum inner-product estimation [2] | O(n² · 1/ε) total queries | ε-additive estimates | State-prep oracles for all rows/cols | **[Theoretical]** |
| Block-encoding / QSVT product [16] | O(polylog n) gates per application to a state | Quantum state only | qRAM/data structure: O(n²) build; readout: Ω(n/ε²) | **[Theoretical]**; end-to-end advantage **[Speculative]** |

---

## 5. Current State of the Art: Software Frameworks

| Framework | Maintainer | Core capabilities | Hardware access | Key limitations (June 2026) |
|---|---|---|---|---|
| PennyLane (arXiv:1811.04968 [19]) | Xanadu | Differentiable programming of hybrid circuits; parameter-shift, adjoint, and hardware-compatible gradients; built-in QNG optimizer; PyTorch/JAX/TF interfaces | Device plugins: IBM, IonQ, Amazon Braket, Rigetti, simulators | Statevector simulation practical to ~30 qubits dense; hardware gradients cost O(d) circuit evaluations per step; no error-corrected backend |
| Qiskit Machine Learning | IBM / ecosystem | EstimatorQNN / SamplerQNN abstractions, quantum kernels, PyTorch connector; executes via Qiskit Runtime primitives | IBM Quantum systems (Heron-class; Nighthawk-class 120-qubit processors [20]) | Shot-based gradient cost; queue latency; utility-scale circuits limited to ~5,000 two-qubit gates on 2025-era Nighthawk, ~7,500 targeted in 2026 [20][21] |
| TensorFlow Quantum (arXiv:2003.02989 [22]) | Google | Cirq-based hybrid quantum-classical models inside TensorFlow; fast batched circuit simulation | Cirq devices / simulators | Effectively in maintenance mode — release cadence has lagged TF/Cirq; primarily a research-simulation tool, not a hardware-training stack |

All three frameworks share the same structural ceiling: they train VQCs of tens of qubits, not quantum subroutines inside billion-parameter classical training loops. No framework today offers any primitive that accelerates a classical LLM gradient step. **[Demonstrated]** state of practice.

**What is tractable for this project today.** Within those ceilings, the experiments worth running in 2026 are: (i) barren-plateau mitigation reproductions (Section 3.4) on 12–24 qubit simulators in PennyLane, since local-cost and identity-block results have crisp, falsifiable predictions [9][10]; (ii) hybrid quantum-adapter fine-tuning — a small VQC head on a frozen classical LM — as a controlled test of whether quantum feature maps add anything at matched parameter count (expected null result; valuable either way); (iii) QAE-based gradient estimation at toy scale (N ≤ 2¹⁰, d ≤ 8) to measure the real constants behind the Section 6 sketch on Heron/Nighthawk-class hardware via Qiskit Runtime. None of these tests "quantum advantage"; all of them build the measurement infrastructure to recognize it if it ever arrives. **[Theoretical]** experiment design.

---

## 6. Theoretical Proof Sketch — O(√N) Gradient Updates for a Transformer Attention Layer

**Label: this entire section is [Theoretical] in its complexity accounting and [Speculative] in its hardware assumptions. It is an asymptotic argument, not a feasibility claim.**

### 6.1 Setup

Consider one attention layer with parameters θ = (W_Q, W_K, W_V) ∈ R^d, d = 3·d_model², and a training set D = {(x_i, y_i)}, i = 1..N. The full-batch gradient component for parameter j is the mean

  g_j(θ) = (1/N) Σ_i ∂ℓ(f_θ(x_i), y_i)/∂θ_j , with |∂ℓ/∂θ_j| ≤ G (bounded, after clipping).

Classical full-batch cost: one forward+backward pass per example — O(N · C_f) where C_f is the per-example pass cost — yielding *all d components at once* (reverse-mode autodiff). **[Proven]**

### 6.2 Assumptions (each one load-bearing)

- **A1 (qRAM):** D is stored in a quantum random access memory supporting coherent addressing Σ_i α_i|i⟩|0⟩ → Σ_i α_i|i⟩|x_i, y_i⟩ in O(polylog N) time [18]. **[Speculative]** — no error-corrected qRAM exists at any scale.
- **A2 (coherent autodiff oracle):** the per-example partial derivative is computable by a reversible circuit U_grad^{(j)} : |i⟩|0⟩ → |i⟩|g_j(i)⟩ at cost Õ(C_f) — i.e., the forward+backward pass compiles to a quantum circuit with only polylogarithmic overhead for reversibility and arithmetic. **[Speculative]** — reversible fixed-point arithmetic typically inflates width and depth by large polylog factors and constants of 10²–10⁴.
- **A3 (amplitude encoding):** the bounded value g_j(i)/G can be rotated into an amplitude in O(1) extra gates. **[Theoretical]** — standard, given A2.
- **A4 (readout granularity):** training tolerates per-component additive gradient error ε = Θ(G/√N) — the same statistical noise floor a classical full-batch computation in floating point effectively has at large N. **[Theoretical]**

### 6.3 Algorithm (pseudocode)

```text
QGE-ATTN(θ, D, j):                         # estimate gradient component j
  1. |s⟩ ← H^{⊗log N} |0⟩                  # uniform index superposition, O(log N)
  2. |s⟩ ← qRAM query: Σ_i (1/√N)|i⟩|x_i,y_i⟩          # A1, O(polylog N)
  3. Apply U_grad^{(j)}: Σ_i (1/√N)|i⟩|x_i,y_i⟩|g_j(i)⟩  # A2, cost Õ(C_f)
  4. Controlled rotation onto flag qubit:
       Σ_i (1/√N)|i⟩|·⟩( sqrt(1-h_i)|0⟩ + sqrt(h_i)|1⟩ ),  h_i = (g_j(i)+G)/(2G)
  5. a ← QAE on the flag qubit with M = O(√N) Grover iterations   # [2]
  6. return ĝ_j = G·(2a − 1)               # additive error O(G/√N) w.h.p.

TRAIN-STEP(θ, D):
  for j = 1..d:  ĝ_j ← QGE-ATTN(θ, D, j)   # d sequential estimations
  θ ← θ − η·ĝ                              # classical optimizer update
```

### 6.4 Complexity Claim

QAE with M Grover iterations yields additive error O(1/M) in the amplitude [2] **[Proven]**; choosing M = O(√N) gives per-component error ε = O(G/√N) using O(√N) coherent evaluations of U_grad. Hence:

- **Quantum cost per update:** O(d · √N · Õ(C_f)) oracle-call work.
- **Classical full-batch cost per update:** O(N · C_f) for *all* d components.

For the *per-component* mean-estimation subproblem at matched precision ε = Θ(G/√N), the quantum cost O(√N) beats the classical sampling cost Θ(N) quadratically. **[Theoretical]** — this is a correct application of proven QAE bounds under A1–A4.

### Table 3 — Gradient-update complexity comparison (one attention layer, batch N, d parameters)

| Method | Cost per update | Precision per component | All-components trick? | Assumptions |
|---|---|---|---|---|
| Classical full-batch backprop | O(N · C_f) | machine precision | Yes — reverse mode gets all d for one pass | None |
| Classical minibatch SGD (B samples) | O(B · C_f), B = O(1)–O(10³) | σ/√B statistical | Yes | None |
| Quantum QAE gradient (this sketch) | O(d · √N · Õ(C_f)) | G/√N additive | **No** — one QAE per component | A1–A4 |

### 6.5 Where the Argument Is Weakest (stated plainly)

1. **The factor d.** Classical backprop amortizes all d derivatives into one pass; the quantum scheme pays d separate QAE runs. The quantum total O(d√N·C_f) beats classical O(N·C_f) only when d ≪ √N — for a single attention layer of a 1B-parameter model, d ≈ 10⁷–10⁸, requiring batch sizes N ≫ 10¹⁴–10¹⁶. No training corpus or batch regime looks like this. **[Proven]** arithmetic, fatal in practice.
2. **The real classical baseline is SGD, not full-batch GD.** SGD with B = O(1) achieves convergence with noisy gradients; the quantum advantage is only over the *full-batch* straw man. Variance-reduction arguments can narrow but not obviously close this gap. **[Theoretical]** objection, well-founded.
3. **A1 (qRAM) and A2 (coherent autodiff) are unconstructed.** Both are **[Speculative]**; qRAM additionally risks dequantization — if the required data structure exists, classical sampling algorithms may inherit much of the advantage [5].
4. **Clock-speed deficit.** Each coherent Õ(C_f) evaluation runs at logical-gate rates ~10⁴–10⁶ ops/s on error-corrected hardware versus ~10¹⁴ FLOP/s on an A100 — eight to ten orders of magnitude (Section 7). A quadratic asymptotic advantage must first repay that constant. **[Demonstrated]** gap (current hardware clock rates), **[Proven]** consequence.

### 6.6 What Would Have to Change for the Sketch to Matter

For completeness, the conditions under which the argument becomes practically interesting, in decreasing order of plausibility:

1. **All-components quantum gradient methods.** Techniques that estimate the full d-dimensional gradient with query cost scaling sublinearly in d (rather than one QAE per component) would remove the dominant factor. Such methods exist in restricted oracle models but require even stronger access assumptions than A2 and have no fault-tolerant implementation analysis at LLM scale; we deliberately do not build the headline claim on them. **[Theoretical]** at best in restricted models; applicability here **[Speculative]**.
2. **Logical clock rates within ~10³× of classical.** Requires faster syndrome extraction, single-shot codes, or non-superconducting modalities with parallel logical operations — no roadmap commits to this. **[Speculative]**
3. **Error-corrected qRAM at ≥10⁹ cells.** Nothing on any vendor roadmap addresses this; even theoretical proposals fight an Ω(N) hardware-cell requirement and noise accumulation across the addressing tree [18]. **[Speculative]**
4. **A training regime that genuinely needs high-precision full-batch gradients.** Some second-order or distillation settings approximate this, but mainstream pretraining does not. **[Speculative]**

Conclusion of the sketch: the O(√N) statement is mathematically sound under A1–A4 but does not imply practical speedup at any plausible parameter regime. We state it as a foundation for identifying *which* assumptions future hardware would have to discharge. **[Theoretical]** overall.

---

## 7. Hardware Requirements vs. an NVIDIA A100

### 7.1 Estimation Methodology (shown, so it can be checked)

1. **Classical baseline.** A100 (80 GB SXM): 312 TFLOP/s dense BF16; assume 45–50% model FLOPs utilization in transformer training → ~1.5×10¹⁴ effective FLOP/s [23]. Training cost ≈ 6P FLOPs per token for a P-parameter model.
2. **Quantum logical clock.** Surface-code logical operations require one round of syndrome extraction per code cycle (~1 µs superconducting); lattice-surgery logical gates cost O(d_code) cycles → ~10⁴–10⁶ logical ops/s. **[Demonstrated]** cycle times (Google Willow, ~1 µs cycles, 0.143% error per cycle at distance 7 [24]).
3. **Logical qubit count.** Registers: index (log₂N ≈ 30–40 qubits), amplitude-encoded activations (log₂ d_model ≈ 12–14 qubits) — negligible. The dominant cost is *reversible arithmetic workspace* for the coherent forward/backward oracle (A2): thousands of logical qubits for fixed-point multiply-accumulate pipelines, scaling roughly with circuit width needed to pipeline one layer. We estimate floors of ~4×10³ (1B), ~8×10³ (7B), ~2×10⁴ (70B) logical qubits, and flag that coherent access to all P weights would additionally require qRAM with O(P) cells — 10⁹–10¹¹ — beyond every published roadmap. **[Speculative]** estimates.
4. **Logical error rate.** Total logical ops per gradient step ≈ d·√N·C̃_f. Even scoping to a *single attention-layer subroutine* (d ≈ 10⁷, √N ≈ 10³, C̃_f ≈ 10⁹) gives ~10¹⁹ ops; requiring ≤1 expected failure per step demands per-op logical error ≲ 10⁻¹⁹. We tabulate the (already heroic) relaxed targets 10⁻¹²–10⁻¹⁵ that correspond to error-mitigated partial workloads.
5. **Physical-per-logical ratio.** Willow demonstrates error suppression Λ ≈ 2.14 per distance increment of 2, with distance-7 logical error 1.43×10⁻³/cycle [24]. Extrapolating: reaching 10⁻¹² needs a factor ~1.4×10⁹ ≈ Λ^28 → code distance ≈ 63 → ≈ 2·d_code² ≈ 8×10³ physical qubits per logical qubit at current physical fidelities. Better physical qubits (higher Λ) reduce this quadratically. **[Demonstrated]** Λ; extrapolation **[Theoretical]**.
6. **Coherence time.** Below threshold, logical lifetime is engineered, not native — the requirement converts to: physical T1/T2 must comfortably support ~1 µs cycles at physical error <10⁻³ (met by Willow-class devices **[Demonstrated]**), and the *wall-clock* per gradient step = (logical ops)×(logical op time) must stay useful: 10¹⁹ ops × 10⁻⁵ s/op ≈ 3×10⁶ years. This single line is the strongest argument in this document. **[Proven]** arithmetic given assumptions 2 and 4.

### Table 4 — Hardware required to outperform one A100 (per attention-layer gradient subroutine)

| Scale | A100 effective rate | Est. logical qubits (floor) | Logical error per op (target) | Physical qubits @ Λ≈2.14 | Implied code distance | Physical T1/T2 required | Wall-clock verdict at 10⁴–10⁶ logical ops/s |
|---|---|---|---|---|---|---|---|
| 1B params | ~1.5×10¹⁴ FLOP/s | ~4×10³ | ≤10⁻¹² | ~3×10⁷ | ~63 | Must support ~1 µs cycles at <10⁻³ physical error (Willow-class: met) | Loses by ≥8 orders of magnitude **[Proven]** arithmetic |
| 7B params | ~1.5×10¹⁴ FLOP/s (per GPU) | ~8×10³ | ≤10⁻¹³ | ~8×10⁷ | ~70 | Must support ~1 µs cycles at <10⁻³ physical error (Willow-class: met) | Loses by ≥9 orders of magnitude |
| 70B params | ~1.5×10¹⁴ FLOP/s (per GPU) | ~2×10⁴ | ≤10⁻¹⁴ | ~2×10⁸ | ~77 | Must support ~1 µs cycles at <10⁻³ physical error (Willow-class: met) | Loses by ≥10 orders of magnitude; qRAM of 10¹¹ cells unaddressed **[Speculative]** |

Notes on the table: (a) "floor" logical-qubit estimates assume amplitude-encoded activations and exclude the O(P)-cell qRAM that coherent weight access would require — including it adds 10⁹–10¹¹ memory cells, which no architecture roadmap addresses; (b) logical error targets are *relaxed* relative to the strict ≤1-failure-per-step budget of methodology step 4, corresponding to partially error-mitigated workloads; (c) the code-distance column extrapolates Willow's measured Λ = 2.14 [24] and improves quadratically with better physical qubits — a future Λ ≈ 4 roughly halves the required distance and quarters the physical overhead; (d) the verdict column compares single-subroutine wall-clock and ignores parallelism across logical patches, which helps throughput but not latency and multiplies qubit counts proportionally. **[Theoretical]** estimates throughout; the underlying arithmetic is **[Proven]** given the stated inputs.

Interpretation: at *any* of these scales, the bottleneck is not qubit count alone but the product (logical clock rate) × (per-op reliability) × (qRAM existence). No combination on any vendor roadmap closes the wall-clock gap for general training; plausible near-term value is confined to small quantum sub-models (VQC adapters, quantum kernels) where the comparison is not against dense GPU matmul throughput. **[Theoretical]**

---

## 8. Timeline Estimate (grounded in June 2026 roadmaps)

Web-verified vendor status as of June 2026:

- **IBM.** Nighthawk (120 qubits, square-lattice tunable couplers) shipped 2025 targeting ~5,000 two-qubit gates; the 2026 roadmap item scales Nighthawk to ~7,500 gates with up to three linked 120-qubit modules (360 qubits), alongside Loon (2025, c-coupler architecture for qLDPC connectivity) and Kookaburra (2026, first quantum-error-corrected module combining logical memory with a logical processing unit) [20][21][25]. IBM Quantum Starling (2029 target): ~200 logical qubits, 100M gates per job; Blue Jay (2033 target): ~2,000 logical qubits, ~1B gates [25]. **[Demonstrated]** for shipped systems; roadmap items **[Speculative]** by definition.
- **Google.** Willow (105 physical qubits) demonstrated below-threshold surface-code error correction: logical error halved (Λ = 2.14) per distance step up to distance-7, logical memory outliving best physical qubits by 2.4×, published in Nature (arXiv:2408.13687) [24]. This validates the scaling premise of QEC — milestone-grade, but ~10³ physical qubits versus the ~10⁷–10⁸ required in Table 4. **[Demonstrated]**
- **IonQ.** Tempo systems shipping in 2026; 256-physical-qubit device with electronic qubit control targeted in 2026; vendor roadmap claims ~1,600 logical qubits by 2028 and 40,000–80,000 logical / 2M physical by 2030, supported by the SkyWater foundry acquisition (~$1.8B, closing 2026) [26][27]. These targets exceed IBM's by orders of magnitude on a shorter clock and should be treated as aggressive vendor projections, not engineering commitments. **[Speculative]**

### Table 5 — Roadmap capability vs. QML-Accelerator requirements

| Year | Best roadmap logical qubits (most conservative credible vendor) | Logical gates per job | Required for Table 4 (1B floor) | Gap |
|---|---|---|---|---|
| 2026 (now) | 0–~1 experimental logical modules (Kookaburra-class) [25]; below-threshold memory **[Demonstrated]** [24] | ~10³–10⁴ physical-gate circuits | 4×10³ logical @ 10⁻¹², 10¹⁹ ops/job | ~9–12 orders of magnitude |
| 2029 | ~200 logical (IBM Starling target) [25] | ~10⁸ | same | ~5–8 orders |
| 2033 | ~2,000 logical (IBM Blue Jay target) [25] | ~10⁹ | same | ~3–6 orders; qRAM still absent |
| 2035+ | extrapolation only | — | — | Earliest conceivable crossover for narrow subroutines **[Speculative]** |

**Reading the three roadmaps against each other.** The vendors are not measuring the same thing, and the table above normalizes conservatively:

- IBM publishes the most engineering-explicit path (specific codes — qLDPC via Loon's c-couplers — specific module counts, and per-year deliverables), which makes its numbers the most auditable and therefore the baseline we adopt for Table 5. **[Demonstrated]** for shipped items; dated targets **[Speculative]**.
- Google has published the strongest *scientific* result (below-threshold scaling, Λ = 2.14 [24]) but does not publish dated logical-qubit-count commitments at IBM's granularity; its milestone framework implies a long-lived logical qubit and logical gate era before any thousand-logical-qubit machine. **[Demonstrated]** result; schedule **[Speculative]**.
- IonQ's 2028 (~1,600 logical) and 2030 (40,000–80,000 logical, 2M physical) figures, if realized, would dominate both — but they outpace IBM's audited path by ~5 years on a smaller demonstrated base (Tempo-class systems shipping in 2026 [27]), and trapped-ion gate speeds (µs–ms) deepen, not narrow, the clock-rate deficit of Section 7. We weight them accordingly. **[Speculative]**

**Timeline judgment.** Even taking vendor roadmaps at face value, the first machines with thousands of logical qubits and ~10⁹-gate budgets arrive ~2033; Table 4 requires ~10¹⁹-op budgets, qRAM, and a 10⁸× clock-gap repayment beyond that. Practical quantum acceleration of mainstream LLM training is therefore not credible before the mid-to-late 2030s, and may never beat classical accelerators for dense linear algebra at all; nearer-term (2029–2033) value, if any, lies in hybrid niches — quantum kernels, sampling subroutines, and small quantum adapter modules where classical baselines are weak. **[Speculative]**, but grounded in **[Demonstrated]** hardware trajectories.

**Recommended tracking signals for this project** (re-evaluate the readiness score when any fires): (i) first demonstration of >10 logical qubits executing >10⁶ logical gates with measured logical error <10⁻⁸; (ii) any peer-reviewed qRAM demonstration beyond ~10³ cells with coherent addressing; (iii) a fault-tolerant compilation study of a reversible transformer block with concrete resource counts; (iv) IBM Kookaburra (2026) and Cockatoo-class module-linking results arriving on schedule [21][25].

---

## 9. Conclusion

The theory surveyed here is real: Grover, QAE, HHL, and QSVT carry proven asymptotic advantages, and our Section 6 sketch shows a mathematically sound O(√N)-query gradient estimator for an attention layer under explicit assumptions. But every path to practical LLM-training acceleration runs through the same four walls — qRAM that does not exist, input/output costs that erase polylog gate counts, a d-factor that backpropagation amortizes and quantum estimation does not, and a clock-speed deficit of eight to ten orders of magnitude that quadratic speedups cannot repay at any realistic batch size. Hardware progress is genuine (Willow's below-threshold QEC; IBM's concrete fault-tolerance roadmap) and should be tracked, not dismissed; the correct posture for this project is theory-forward research and small hybrid prototypes, with no near-term expectation of training acceleration.

**Readiness Score: 2/10** — proven primitives and demonstrated error-correction milestones exist, but no end-to-end advantage mechanism survives honest input/output and clock-rate accounting on any verified roadmap before the mid-2030s.

### Notation and Symbols Used Throughout

| Symbol | Meaning |
|---|---|
| N | Number of training examples in a batch / search-space size |
| d | Number of trainable parameters (for one attention layer, d = 3·d_model²) |
| n | Matrix dimension (Section 4) or qubit count (Section 3), per local context |
| κ | Condition number of a linear system |
| s | Row sparsity of a matrix |
| ε | Additive estimation error / target precision |
| C_f | Cost of one classical per-example forward+backward pass |
| Õ(·) | Big-O suppressing polylogarithmic factors |
| ω | Matrix multiplication exponent (best known: ω < 2.371339 [14]) |
| Λ | Error-suppression factor per code-distance increment of 2 (Willow: 2.14 [24]) |
| P | Total model parameter count (1B / 7B / 70B scales) |

---

## 10. References

1. L. K. Grover, "A fast quantum mechanical algorithm for database search," Proc. 28th ACM STOC (1996). arXiv:quant-ph/9605043. https://arxiv.org/abs/quant-ph/9605043
2. G. Brassard, P. Høyer, M. Mosca, A. Tapp, "Quantum Amplitude Amplification and Estimation," Contemporary Mathematics 305 (2002). arXiv:quant-ph/0005055. https://arxiv.org/abs/quant-ph/0005055
3. A. W. Harrow, A. Hassidim, S. Lloyd, "Quantum algorithm for linear systems of equations," Physical Review Letters 103, 150502 (2009). arXiv:0811.3171. https://arxiv.org/abs/0811.3171
4. S. Aaronson, "Read the fine print," Nature Physics 11, 291–293 (2015). https://www.nature.com/articles/nphys3272
5. E. Tang, "A quantum-inspired classical algorithm for recommendation systems," Proc. 51st ACM STOC (2019). arXiv:1807.04271. https://arxiv.org/abs/1807.04271
6. J. Preskill, "Quantum Computing in the NISQ era and beyond," Quantum 2, 79 (2018). arXiv:1801.00862. https://arxiv.org/abs/1801.00862
7. J. Stokes, J. Izaac, N. Killoran, G. Carleo, "Quantum Natural Gradient," Quantum 4, 269 (2020). arXiv:1909.02108. https://arxiv.org/abs/1909.02108
8. J. R. McClean, S. Boixo, V. N. Smelyanskiy, R. Babbush, H. Neven, "Barren plateaus in quantum neural network training landscapes," Nature Communications 9, 4812 (2018). arXiv:1803.11173. https://arxiv.org/abs/1803.11173
9. M. Cerezo, A. Sone, T. Volkoff, L. Cincio, P. J. Coles, "Cost function dependent barren plateaus in shallow parametrized quantum circuits," Nature Communications 12, 1791 (2021). arXiv:2001.00550. https://arxiv.org/abs/2001.00550
10. E. Grant, L. Wossnig, M. Ostaszewski, M. Benedetti, "An initialization strategy for addressing barren plateaus in parametrized quantum circuits," Quantum 3, 214 (2019). arXiv:1903.05076. https://arxiv.org/abs/1903.05076
11. A. Skolik, J. R. McClean, M. Mohseni, P. van der Smagt, M. Leib, "Layerwise learning for quantum neural networks," Quantum Machine Intelligence 3, 5 (2021). arXiv:2006.14904. https://arxiv.org/abs/2006.14904
12. T. Volkoff, P. J. Coles, "Large gradients via correlation in random parameterized quantum circuits," Quantum Science and Technology 6, 025008 (2021). arXiv:2005.12200. https://arxiv.org/abs/2005.12200
13. V. Strassen, "Gaussian elimination is not optimal," Numerische Mathematik 13, 354–356 (1969).
14. J. Alman, R. Duan, V. Vassilevska Williams, Y. Xu, Z. Xu, R. Zhou, "More Asymmetry Yields Faster Matrix Multiplication," Proc. SODA 2025. arXiv:2404.16349. https://arxiv.org/abs/2404.16349
15. V. Vassilevska Williams, Y. Xu, Z. Xu, R. Zhou, "New Bounds for Matrix Multiplication: from Alpha to Omega," Proc. SODA 2024. https://epubs.siam.org/doi/10.1137/1.9781611977912.134
16. A. Gilyén, Y. Su, G. H. Low, N. Wiebe, "Quantum singular value transformation and beyond: exponential improvements for quantum matrix arithmetics," Proc. 51st ACM STOC (2019). arXiv:1806.01838. https://arxiv.org/abs/1806.01838
17. I. Kerenidis, A. Prakash, "Quantum Recommendation Systems," Proc. ITCS 2017. arXiv:1603.08675. https://arxiv.org/abs/1603.08675
18. V. Giovannetti, S. Lloyd, L. Maccone, "Quantum random access memory," Physical Review Letters 100, 160501 (2008). arXiv:0708.1879. https://arxiv.org/abs/0708.1879
19. V. Bergholm et al., "PennyLane: Automatic differentiation of hybrid quantum-classical computations," arXiv:1811.04968. https://arxiv.org/abs/1811.04968
20. "IBM unveils new 'Quantum Nighthawk' 120-qubit processor and software stack," Tom's Hardware (2025). https://www.tomshardware.com/tech-industry/semiconductors/ibm-unveils-new-120-qubit-processor-and-software-stack
21. IBM Quantum roadmap, 2026 milestones, IBM Technology Atlas. https://www.ibm.com/roadmaps/quantum/2026/
22. M. Broughton et al., "TensorFlow Quantum: A Software Framework for Quantum Machine Learning," arXiv:2003.02989. https://arxiv.org/abs/2003.02989
23. NVIDIA A100 Tensor Core GPU datasheet (312 TFLOPS BF16 dense, 80 GB HBM2e). https://www.nvidia.com/en-us/data-center/a100/
24. Google Quantum AI and Collaborators, "Quantum error correction below the surface code threshold," Nature 638, 920–926 (2025). arXiv:2408.13687. https://www.nature.com/articles/s41586-024-08449-y
25. "IBM lays out clear path to fault-tolerant quantum computing" (Starling 2029: 200 logical qubits / 100M gates; Blue Jay 2033: 2,000 logical qubits / 1B gates), IBM Quantum Blog (2025). https://www.ibm.com/quantum/blog/large-scale-ftqc
26. "IonQ's Quantum Roadmap and Foundry Strategy Through 2030" (Tempo shipping 2026; 256-qubit EQC device 2026; ~1,600 logical qubits 2028; 2M qubits by 2030; SkyWater acquisition). https://finance.yahoo.com/news/ionqs-quantum-roadmap-foundry-strategy-162400233.html
27. "IonQ Expands QuantumBasel Partnership with Forte Enterprise and Tempo Systems," HPCwire. https://www.hpcwire.com/off-the-wire/ionq-expands-quantumbasel-partnership-with-forte-enterprise-and-tempo-systems/
28. E. A. Cherrat, I. Kerenidis, N. Mathur, J. Landman, M. Strahm, Y. Y. Li, "Quantum Vision Transformers," Quantum 8, 1265 (2024). arXiv:2209.08167. https://arxiv.org/abs/2209.08167 — (related work: quantum attention mechanisms with asymptotic run-time analysis.)
