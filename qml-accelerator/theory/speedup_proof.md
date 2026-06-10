# QGE-ATTN: An O(d·√N)-Query Gradient Estimator for a Transformer Attention Layer — Formal Statement and Proof Sketch

**Project:** quantum-hybrid-research / qml-accelerator
**Source of truth:** `docs/research/01-qml-accelerator.md`, §6 (proof sketch), §2.0 (query-model translation losses), §6.5–6.6 (weaknesses and escape conditions). This document is the Stage 4 theory deliverable of `docs/workflows/01-qml-workflow.md`.

> **Label (carried verbatim from the research doc §6):** this entire document is **[Theoretical]** in its complexity accounting and **[Speculative]** in its hardware assumptions. It is an asymptotic argument, not a feasibility claim.

---

## 1. Scope and Epistemic Status

This document restates the research doc's §6 proof sketch as a standalone theorem-style argument: definitions, assumptions, claim, proof sketch, weaknesses, and the honest corollary that **no realistic crossover exists**. It deliberately proves no more than the research doc claims. Tags follow the project convention: **[Proven]** (mathematically proven), **[Demonstrated]** (shown on real hardware), **[Theoretical]** (rigorous but unproven in practice), **[Speculative]** (extrapolation or conjecture).

---

## 2. Definitions

| Symbol | Definition |
|---|---|
| θ = (W_Q, W_K, W_V) ∈ ℝ^d | Parameters of one attention layer; d = 3·d_model² |
| D = {(x_i, y_i)}, i = 1..N | Training set (batch) of N examples |
| g_j(θ) = (1/N) Σ_i ∂ℓ(f_θ(x_i), y_i)/∂θ_j | Full-batch gradient component j, with \|∂ℓ/∂θ_j\| ≤ G (bounded, after clipping) |
| C_f | Cost of one classical per-example forward+backward pass |
| Õ(·) | Big-O suppressing polylogarithmic factors |
| ε | Additive estimation error / target precision |
| QAE | Quantum Amplitude Estimation: given a unitary A preparing a state with success amplitude √a, estimates a to additive error ε with O(1/ε) applications of A and A† — **[Proven]** (Brassard, Høyer, Mosca, Tapp 2000, arXiv:quant-ph/0005055 [2]) |

**Classical baseline (definition, not assumption).** Classical full-batch cost is one forward+backward pass per example — O(N · C_f) — yielding *all d components at once* via reverse-mode autodiff. **[Proven]** (research doc §6.1). The honest practical baseline is minibatch SGD at O(B · C_f), B = O(1)–O(10³), which is flat in N (research doc §6.5(2)).

---

## 3. Assumptions A1–A4 (each one load-bearing)

The tags below are exactly the research doc §6.2 tags. Per the workflow ground rules, every **[Speculative]** assumption is modeled in code as a labeled assumption with a tunable constant — never silently treated as free. The right-hand column maps each assumption to the constant in `qml-accelerator/benchmarks/complexity_analysis.py` (`CostConstants`) that models it.

| # | Assumption | Tag | Code constant in `complexity_analysis.py` |
|---|---|---|---|
| **A1 (qRAM)** | D is stored in a quantum random access memory supporting coherent addressing Σ_i α_i\|i⟩\|0⟩ → Σ_i α_i\|i⟩\|x_i, y_i⟩ in O(polylog N) time [18]. | **[Speculative]** — no error-corrected qRAM exists at any scale. | Treated as O(polylog N) access in the query-model curves only; the wall-clock model never grants it for free — the matvec op carries the Ω(n²) qRAM/data-structure build explicitly (`_matvec_hhl_classical_readout`, framing notes). |
| **A2 (coherent autodiff oracle)** | The per-example partial derivative is computable by a reversible circuit U_grad^{(j)} : \|i⟩\|0⟩ → \|i⟩\|g_j(i)⟩ at cost Õ(C_f) — the forward+backward pass compiles to a quantum circuit with only polylogarithmic overhead for reversibility and arithmetic. | **[Speculative]** — reversible fixed-point arithmetic typically inflates width and depth by large polylog factors and constants of 10²–10⁴. | `oracle_synthesis_low = 1e2`, `oracle_synthesis_high = 1e4` (research doc §2.0(1)); swept over the full range in the crossover charts. |
| **A3 (amplitude encoding)** | The bounded value g_j(i)/G can be rotated into an amplitude in O(1) extra gates. | **[Theoretical]** — standard, given A2. | O(1); no constant needed (absorbed into Õ(C_f)). |
| **A4 (readout granularity)** | Training tolerates per-component additive gradient error ε = Θ(G/√N) — the same statistical noise floor a classical full-batch computation in floating point effectively has at large N. | **[Theoretical]** | Sets the QAE iteration count M = O(√N) in the cost model `_grad_quantum_qge`; the precision axis of the mean-estimation panel uses `epsilon`. |

In addition (not an assumption of the sketch, but required for any wall-clock translation, research doc §2.0(3)/§7.1): the logical clock rate is 10⁴–10⁶ ops/s vs. ~1.5×10¹⁴ effective FLOP/s on an A100 — a 10⁸–10¹⁰× deficit. **[Demonstrated]** ~1 µs physical cycle times [24]; **[Theoretical]** logical-rate extrapolation; **[Proven]** consequence. Modeled by `logical_rate_low/high` and `classical_rate`.

---

## 4. Claim

**Theorem (per-component quantum gradient estimation; [Theoretical] under A1–A4).**
Under A1–A4, for each parameter index j, the algorithm QGE-ATTN estimates g_j(θ) to additive error ε = O(G/√N) with high probability using O(√N) coherent evaluations of U_grad^{(j)}, i.e. O(√N · Õ(C_f)) oracle-call work. Consequently:

- **Quantum cost per full update:** O(d · √N · Õ(C_f)) oracle-call work (one QAE run per component; there is no all-components trick).
- **Classical full-batch cost per update:** O(N · C_f) for *all* d components.

For the *per-component* mean-estimation subproblem at matched precision ε = Θ(G/√N), the quantum cost O(√N) beats the classical sampling cost Θ(N) quadratically. **[Theoretical]** — a correct application of proven QAE bounds under A1–A4 (research doc §6.4).

---

## 5. Proof Sketch

### 5.1 Algorithm (pseudocode, reproduced from research doc §6.3)

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

### 5.2 Argument

1. **Steps 1–2 (superposition + load).** Hadamards cost O(log N); under A1 the qRAM query costs O(polylog N). The state is Σ_i (1/√N)|i⟩|x_i, y_i⟩.
2. **Step 3 (coherent gradient oracle).** Under A2, one application of U_grad^{(j)} costs Õ(C_f) and writes g_j(i) into a register, coherently across all i.
3. **Step 4 (amplitude encoding).** Under A3, the shifted-and-scaled value h_i = (g_j(i)+G)/(2G) ∈ [0,1] (well-defined by the clipping bound \|∂ℓ/∂θ_j\| ≤ G) rotates onto a flag qubit in O(1) extra gates. The probability of measuring the flag as |1⟩ is a = (1/N) Σ_i h_i = (ḡ_j + G)/(2G), where ḡ_j = g_j(θ).
4. **Step 5 (amplitude estimation).** QAE with M Grover iterations yields additive error O(1/M) in the amplitude a — **[Proven]** [2]. Choosing M = O(√N) gives error O(1/√N) in a, hence (by Step 6's affine map ĝ_j = G·(2a − 1)) additive error ε = O(G/√N) in the gradient component, with high probability, using O(√N) coherent evaluations of U_grad^{(j)} (each Grover iteration uses the state-preparation unitary and its inverse a constant number of times).
5. **Per-update total.** TRAIN-STEP runs d sequential QGE-ATTN estimations: O(d · √N · Õ(C_f)) oracle-call work. Under A4, the precision ε = Θ(G/√N) suffices for the update; this is the matched-precision comparison point. ∎ (sketch)

### 5.3 Cost comparison (research doc Table 3, reproduced)

| Method | Cost per update | Precision per component | All-components trick? | Assumptions |
|---|---|---|---|---|
| Classical full-batch backprop | O(N · C_f) | machine precision | Yes — reverse mode gets all d for one pass | None |
| Classical minibatch SGD (B samples) | O(B · C_f), B = O(1)–O(10³) | σ/√B statistical | Yes | None |
| Quantum QAE gradient (this sketch) | O(d · √N · Õ(C_f)) | G/√N additive | **No** — one QAE per component | A1–A4 |

---

## 6. Where the Argument Is Weakest (stated plainly, per research doc §6.5)

1. **The factor d.** Classical backprop amortizes all d derivatives into one pass; the quantum scheme pays d separate QAE runs. The quantum total O(d·√N·C_f) beats classical O(N·C_f) only when d ≪ √N — for a single attention layer of a 1B-parameter model, d ≈ 10⁷–10⁸, requiring batch sizes N ≫ 10¹⁴–10¹⁶. No training corpus or batch regime looks like this. **[Proven]** arithmetic, fatal in practice.
2. **The real classical baseline is SGD, not full-batch GD.** SGD with B = O(1) achieves convergence with noisy gradients; the quantum advantage is only over the *full-batch* straw man. Variance-reduction arguments can narrow but not obviously close this gap. **[Theoretical]** objection, well-founded.
3. **A1 (qRAM) and A2 (coherent autodiff) are unconstructed.** Both are **[Speculative]**; qRAM additionally risks dequantization — if the required data structure exists, classical sampling algorithms may inherit much of the advantage (Tang [5]).
4. **Clock-speed deficit.** Each coherent Õ(C_f) evaluation runs at logical-gate rates ~10⁴–10⁶ ops/s on error-corrected hardware versus ~10¹⁴ FLOP/s on an A100 — eight to ten orders of magnitude (research doc §7). A quadratic asymptotic advantage must first repay that constant. **[Demonstrated]** gap (current hardware clock rates), **[Proven]** consequence.

---

## 7. Corollary: No Realistic Crossover

**Corollary ([Proven] arithmetic given the stated inputs; conclusion [Theoretical]).**
Let R_c ≈ 1.5×10¹⁴ FLOP/s (A100 effective rate, §7.1), R_q ∈ [10⁴, 10⁶] logical ops/s, and c_or ∈ [10², 10⁴] the oracle-synthesis constant (§2.0). Then:

- **Query model (constants ignored):** QGE-ATTN undercuts classical full-batch backprop only when d·√N < N, i.e. **N > d²**. For d ≈ 10⁷–10⁸ this means N ≫ 10¹⁴–10¹⁶ — beyond any training corpus or batch regime.
- **Wall clock (constants applied):** the crossover condition becomes N > (d · c_or · R_c/R_q)². Even at the most quantum-favourable end (d = 10⁷, c_or = 10², R_c/R_q = 1.5×10⁸), this is N ≳ 10³⁴.
- **Against the honest baseline:** versus minibatch SGD at O(B·C_f) — flat in N — the quantum curve never crosses at any N.

Hence **no realistic crossover exists** for quantum gradient estimation in LLM training under A1–A4 plus honest wall-clock accounting. This is the research doc's conclusion (§6.6 closing): the O(√N) statement is mathematically sound under A1–A4 but does not imply practical speedup at any plausible parameter regime; its value is identifying *which* assumptions future hardware would have to discharge. The companion script `qml-accelerator/benchmarks/complexity_analysis.py` computes and plots exactly this corollary.

---

## 8. What Would Have to Change (research doc §6.6, abridged)

In decreasing order of plausibility:

1. **All-components quantum gradient methods** with query cost sublinear in d — exist only in restricted oracle models with even stronger access assumptions than A2; no fault-tolerant resource analysis at LLM scale. **[Theoretical]** at best in restricted models; applicability here **[Speculative]**. The headline claim is deliberately not built on them.
2. **Logical clock rates within ~10³× of classical.** No roadmap commits to this. **[Speculative]**
3. **Error-corrected qRAM at ≥10⁹ cells.** Nothing on any vendor roadmap; theoretical proposals fight an Ω(N) hardware-cell requirement [18]. **[Speculative]**
4. **A training regime that genuinely needs high-precision full-batch gradients.** Mainstream pretraining does not. **[Speculative]**

---

## 9. References

Numbered citations follow the research doc's reference list (`docs/research/01-qml-accelerator.md`, §10):

- [2] G. Brassard, P. Høyer, M. Mosca, A. Tapp, "Quantum Amplitude Amplification and Estimation," Contemporary Mathematics 305 (2002). arXiv:quant-ph/0005055.
- [5] E. Tang, "A quantum-inspired classical algorithm for recommendation systems," Proc. 51st ACM STOC (2019). arXiv:1807.04271.
- [18] V. Giovannetti, S. Lloyd, L. Maccone, "Quantum random access memory," Physical Review Letters 100, 160501 (2008). arXiv:0708.1879.
- [23] NVIDIA A100 Tensor Core GPU datasheet (312 TFLOPS BF16 dense).
- [24] Google Quantum AI and Collaborators, "Quantum error correction below the surface code threshold," Nature 638, 920–926 (2025). arXiv:2408.13687.
