# Educational 3D Quantum Visualization for the Web: Feasibility Study

**Document:** docs/research/04-quantum-viz-education.md
**Status:** Research document — feasibility study
**Last updated:** June 2026
**Epistemic convention:** Every claim in this document carries one of four tags: **[Proven]** (mathematically proven), **[Demonstrated]** (experimentally shown — for this document, verified live against primary sources, npm registries, or source code), **[Theoretical]** (rigorous but unproven in practice — here, design recommendations synthesized from verified findings), **[Speculative]** (extrapolation or conjecture). Untagged sentences are context, not claims.

---

## 1. Abstract

This document assesses the feasibility of building an educational, interactive 3D visualization that teaches how a quantum computer works at the simplest level, embedded in a React/Next.js website — and finds it **highly feasible**. Every layer of the stack is solved and verified: the Next.js App Router + react-three-fiber architecture is a documented pattern with an official starter (persistent canvas, ~79 kB first-load JS) **[Demonstrated]**; in-browser quantum simulation at the 1–2 qubits a beginner site needs sits two orders of magnitude below the verified performance walls (pure JavaScript handles ~7 qubits before slowing; Quirk's WebGL engine reaches 16) **[Demonstrated]**; and MIT-licensed off-the-shelf engines exist, benchmarked at 15 ms for a 2-qubit circuit **[Demonstrated]**. The hard part is not engineering but pedagogy — and the pedagogy is research-guided rather than guesswork: peer-reviewed physics-education research specifies which visual representations teach which concepts (and which create misconceptions), Aaronson's Minus-Sign Test dictates that phase and interference must be visible, and Quirk provides a verified interaction gold standard (no run button, sub-0.1 s continuous feedback). The recommended build is four components — a Bloch-sphere hero with gates-as-rotations, a touch-first gate playground with circle-notation displays, a 2-qubit product-vs-entangled comparison, and a measurement-collapse animation — all client components, with this repository's existing Python statevector emulator as the porting source and test oracle for the simulation core. Readiness score: 8/10.

---

## 2. Methodology Note

Unlike documents 01–03 in this series, which survey theory, this study was produced by a multi-agent deep-research harness performing web research with **per-claim adversarial verification**. Each of the top claims was independently checked by 3 verifier agents against the primary sources — live fetches of repositories, npm registries, documentation, and papers, as of June 2026 — and survives only on a majority vote. The pipeline:

| Stage | Count |
|---|---|
| Research angles fanned out | 5 (framework integration, 3D stack, browser simulation engines, pedagogy & misconceptions, reusable repos) |
| Sources fetched | 21 |
| Claims extracted | 104 |
| Claims adversarially verified (3 votes each) | 25 |
| Confirmed (3–0) | 24 |
| Refuted (0–3) | 1 (reported in §3.4) |
| Findings after synthesis | 11 |

Every finding in this document retains its vote count: a claim marked **(3–0)** means three independent verifiers confirmed it against primary sources and none dissented. Verifier *corrections* (places where a source was being over-read) are folded in and flagged inline.

Claim tags follow the repository convention with one mapping note: because this is web/engineering research rather than physics, most verified facts here are **[Demonstrated]** (confirmed live against sources, npm, or running code) rather than [Proven]; design recommendations derived from those facts are **[Theoretical]**. Section 6, the synthesized architecture plan, is **[Theoretical]** as a unit — its inputs are all 3–0 findings, but the plan itself is inference, not a verified claim.

**Verified-coverage gaps (silence, not refutation).** Several sub-questions produced no claims that survived verification, so this document is deliberately silent on them:

- WebGPU readiness in 2026 (three.js `WebGPURenderer` / TSL node-material maturity, and whether WebGPU buys anything for scenes this small);
- honest tradeoffs for Babylon.js, Spline, or Unity-WebGL-embed alternatives;
- Vercel-specific hosting details;
- bundle-size engineering beyond the starter's self-reported ~79 kB;
- concrete accessibility patterns for WebGL content (keyboard navigation, `aria-live`, screen-reader fallbacks).

These remain open questions (collected in §8.1), flagged where they touch the plan.

---

## 3. Next.js App Router Architecture

### 3.1 The Persistent-Canvas Pattern (react-three-next)

The pattern is solved and documented. The official pmndrs starter, react-three-next, demonstrates the exact architecture this site needs **[Demonstrated]** (3–0) [1][2]:

- a single persistent WebGL `<Canvas>` mounted in the root layout that is **not unmounted across route navigations** ("Canvas is not getting unmounted while navigating between pages");
- tunnel-rat plus drei's `<View>` component, using `gl.scissor` viewport segmentation ("for better performances it uses gl.scissor to cut the viewport into segments"), to render 3D scenes into arbitrary DOM divs;
- ~79 kB first-load JS by the starter's own metrics.

One WebGL context therefore serves a Bloch-sphere hero *and* multiple inline demos on the same page — precisely the layout Section 6 requires. Verifiers confirmed the pattern in code, not just prose: `app/layout.jsx` renders a fixed-position `<Scene>` (the R3F Canvas) alongside `children`; `tunnel-rat ^0.1.2` appears in package.json; `src/components/canvas/View.jsx` wraps drei's View. The R3F docs call it "our official next.js starter" [2].

### 3.2 The R3F ↔ React Version Constraint

React Three Fiber enforces a strict peer-dependency pairing — the one hard constraint in the entire stack **[Demonstrated]** (3–0) [2]:

| R3F major | Required React | npm peerDependencies (verified live, June 2026) |
|---|---|---|
| v8 (fiber@8.18.0) | React 18 | `react ">=18 <19"` |
| v9 (fiber@9.6.1) | React 19 | `react ">=19 <19.3"` |

The ranges are mutually exclusive and machine-enforced by package managers; drei majors follow fiber. The docs state it verbatim: "@react-three/fiber@8 pairs with react@18, @react-three/fiber@9 pairs with react@19." The project's React version dictates the entire 3D dependency tree — check this *first*, before any other architectural decision.

### 3.3 Client-Component Boundaries

All 3D rendering lives in `'use client'` components — WebGL has no server-side rendering story, and the App Router default of server components means every Canvas, View, and interactive demo must sit below an explicit client boundary. Static copy, layout, and navigation stay in server components for free; the persistent-Canvas starter already structures itself this way [1]. **[Theoretical]** design consequence of the verified architecture.

### 3.4 Caveats and the One Refuted Claim

**The starter is a pattern, not a base.** react-three-next was last pushed 2024-06-21 and pins Next 14 / R3F v8, with open issues requesting Next 15/16 + React 19 updates. Treat it as a *reference for the pattern* — persistent Canvas, View portals, tunnel-rat — re-implemented on current Next.js, not as a copy-paste foundation. **[Demonstrated]** staleness (3–0) [1]. Whether the pattern works unchanged on Next 15/16 with React 19 and Turbopack is an open question (§8.1).

**Refuted claim (0–3), recorded per convention:** *"Using R3F in Next.js ≥13.1 requires adding `'three'` to `transpilePackages` in next.config.js."* Three verifiers rejected the *necessity* claim against the current docs [2]. The option exists and the starter mentions it; do not treat it as a requirement — verify against the Next.js version actually used during setup.

---

## 4. In-Browser Quantum Simulation

### 4.1 The Verified Performance Ladder

Three real-world data points bound what browsers can simulate, all **[Demonstrated]** (3–0) [3][4][5][6]:

| Rung | Engine | Verified limit |
|---|---|---|
| Pure JavaScript statevector | Quirk's first implementation | "Things got slow around 7 qubits" (Gidney, first-person) [4] |
| WebGL GPU compute | Quirk (98.2% JavaScript orchestrating shaders) | ~100× speedup; responsive to ~14 qubits, capped at 16 [4][5] |
| Rust → WebAssembly, sparse | Quantum Flytrap Virtual Lab | Billion-dimensional state spaces (three entangled photons); runs in-browser at ~1.5× native cost, 30–150 µs typical operations [6] |

Two verifier-supplied qualifications: Quirk's 16-qubit cap partly reflects WebGL texture and real-time-animation constraints, not a universal browser CPU ceiling — it is a data point for *real-time interactive* simulation specifically **[Demonstrated]** [4][5]. And the Flytrap material is co-authored by Flytrap's founder (self-reporting), though peer-reviewed and independently corroborated [6].

The implication for this project: a 1–2 qubit teaching site (4 complex amplitudes) sits roughly two orders of magnitude below the *lowest* rung of this ladder and runs at 60 fps in plain TypeScript with no special engine. **[Demonstrated]** consequence (3–0).

### 4.2 Off-the-Shelf Option: quantum-circuit (npm)

The quantum-circuit package is MIT-licensed and actively published — version 0.9.247 on 2026-02-09, the *only* currently-maintained dependency among the reference implementations surveyed (§7). **[Demonstrated]** (3–0) [3]:

- A verifier independently benchmarked it: a **2-qubit/9-gate circuit simulates in 15 ms** — roughly 6× inside a 100 ms feedback budget (§5.4) before any optimization.
- Its key implementation pattern — storing the statevector as a **sparse map keyed by basis index**, holding only non-zero amplitudes (worst case 2^n entries) — was confirmed in source (`lib/quantum-circuit.js`: `this.state = {}`). The pattern is directly reusable even if the engine itself is not adopted.
- Honest caveat, folded in by verifiers: the README's "smoothly runs 20+ qubit simulations" overstates the top end. A 78-gate, 20-qubit circuit took **42 s** (CNOT ~536 ms/gate on a dense state) at ~1 GB RSS — batch-feasible, not real-time. Irrelevant at 1–2 qubits, but do not repeat the "smoothly 20+" claim unqualified.

### 4.3 Recommendation: Port This Repository's Emulator

The recommended engine is neither dependency: a hand-rolled **~150-line TypeScript statevector core**, ported from this repository's existing numpy emulator (`quantum-linux/emulator/qcpu.py`, 852 lines — only the gate-application core is needed for 2 qubits). **[Theoretical]** recommendation; its feasibility bounds are **[Demonstrated]**. Concretely:

- **Scope of the port:** complex amplitudes as `[re, im]` pairs (or a flat `Float64Array`), 2×2 single-qubit gate application, controlled-gate application for CNOT/CZ, and Born-rule measurement with a seeded PRNG. The gate set the demos need — H, X, Y, Z, S, T, RX/RY/RZ, CNOT — is already implemented and tested in `qcpu.py`.
- **Why hand-rolled:** four amplitudes is not a workload; a dependency-free core keeps the bundle minimal (§3.1's ~79 kB budget), and quantum-circuit's sparse-map pattern can be adopted if the site ever grows past 2 qubits [3].
- **The decisive advantage — verification:** the repository's **228-test pytest suite** already exercises the Python emulator (Bell states, teleportation, per-instruction amplitude traces via `qrun.py --trace --seed`). The TS port is validated against it as a **cross-language oracle**: run identical circuits with identical seeds on both engines and compare amplitudes to machine precision. The simulation layer then inherits the same evidence discipline as the rest of this repository.
- **Headroom check:** a 2-qubit engine needs 4 amplitudes against a verified 7-qubit (128-amplitude) pure-JS wall [4], and the 15 ms benchmark shows even a general-purpose unoptimized engine clears the latency budget [3]. Both bounds are **[Demonstrated]** (3–0).

---

## 5. Pedagogy

This is the core section. The engineering above is commodity; what distinguishes a quantum explainer that teaches from one that entertains is documented in peer-reviewed physics-education research (PER), and every design choice below traces to it.

### 5.1 The Minus-Sign Test: Phase Must Be Visible

The most common beginner trap is presenting superposition as a qubit being "0 and 1 at the same time" — the spinning-coin framing. This fails because it cannot distinguish quantum mechanics from classical statistical uncertainty: a spinning coin is *also* "heads and tails at once" in the ignorance sense, and the framing omits the one thing that is actually quantum — relative phase and negative amplitudes. The peer-reviewed source states it verbatim: "Telling someone that it is possible to have a qubit in the |0⟩ and |1⟩ state simultaneously ... fails to distinguish between statistical uncertainty and quantum mechanics" [6].

Aaronson's **Minus-Sign Test** holds that any good popularization must at minimum mention interference between positive and negative amplitudes — "the defining feature of quantum mechanics." **[Demonstrated]** (3–0; attribution chain to Aaronson's 2011 post verified) [6][7].

Design consequences:

- **Every superposition visual on the site must encode phase, not just probability.** A Hadamard on |0⟩ and a Hadamard on |1⟩ must *look different* (they differ only by a minus sign).
- Applying H twice must **visibly interfere** back to a basis state — interference as something the learner watches happen, not a word in a caption.
- Verifier nuance, recorded honestly: the test formally requires *mentioning* minus signs and the source says "a common problem" rather than literally "the most common"; "must show" is a mild design extension this document adopts deliberately. **[Theoretical]** extension of a **[Demonstrated]** principle.

### 5.2 The Bloch Sphere Cannot Carry the Whole Course

The Bloch sphere — the obvious centerpiece for a 3D site — **cannot represent entanglement**: an entangled qubit's reduced state is mixed (interior of the ball), so the sphere is structurally silent on the one concept beginners most want explained. It must therefore be *combined* with other representations, not used alone — the study below states this verbatim ("representations such as the Bloch sphere, cannot be used for all concepts (e.g. entanglement), so it must be used in combination with other qubit representations"). **[Demonstrated]** (3–0), and textbook quantum information [10].

An expert-rating study (Qerimi et al., EPJ Quantum Technology 2025: **21 international experts, 16 criteria**) quantifies the pairing **[Demonstrated]** (3–0) [10]:

| Representation | Measurement / superposition / probability (beginner) | Relative phase |
|---|---|---|
| Circle Notation (flat amplitude/phase) | **4.02 ± 1.07** (highest) | lower |
| Qake pie-chart model | **3.88 ± 1.05** | lower |
| Bloch sphere | significantly lower (χ²(3) = 37.258, p < .001, d = 0.43–0.51) | **4.56 ± 0.76** (wins) |
| Quantum Bead | significantly lower | — |

The Bloch sphere wins exactly one category — relative phase — which is precisely the gates-as-rotations story it should be reserved for. Experts also rated representations as carrying **measurably different misconception risks** tied to shape, measurement depiction, and entanglement requirements — e.g., the Bloch sphere inviting the belief that a qubit literally *is* a small sphere [10].

Honest qualifiers, per the verifiers: these are expert-rated misconception *potentials*, not measured learner outcomes; and a 2025 follow-up (arXiv:2507.21721) found no learning-outcome difference between Bloch sphere and Quantum Bead, with the Bloch sphere *better* on single-qubit task efficiency. Representation choice matters most for misconception avoidance, not raw learning speed. **[Demonstrated]** caveat [10].

Design consequence: **pair representations.** 3D Bloch sphere for single-qubit rotations and phase; synced flat circle-notation panels for amplitudes and probability; and a non-Bloch representation for anything 2-qubit.

### 5.3 Documented Misconceptions the Demos Must Counter

Hu, Li, and Singh (Phys. Rev. PER **20**, 020108, 2024 — top PER journal, leading group, validated pre/post instruments) catalog the specific errors introductory students make. Three bind directly on this site's design, all **[Demonstrated]** (3–0) [11]:

1. **"Any superposition is entangled."** Students "easily make the overgeneralization that any multi-qubit state that is a linear combination (i.e., superposition) of the possible basis states is an entangled state" — only non-factorable states are. A tutorial explicitly teaching the product-state vs non-factorable distinction raised correctness from **~50% to ~80%**. Design consequence: the 2-qubit demo must contrast a factorable state like (|00⟩+|01⟩)/√2 — which *looks* like "both at once" but is boringly separable — against a Bell state, side by side.
2. **The 2^N reasoning primitive.** Loose "exponential advantage" framing leads students to replace quantities N with 2^N wholesale — believing "2^N qubits must be initialized and 2^N bits of information are obtained as the output." Design consequence: the site must never say "a quantum computer is in 2^N states at once" without immediately unpacking what amplitudes are and what measurement actually returns.
3. **Gates-as-collapse.** Asked to construct a single-qubit gate, students' answers "almost always were projective measurement gates" — non-unitary operations that collapse the state — while rotation-of-state answers were graded "perfectly acceptable." Design consequence: animate every gate as a smooth, reversible **rotation**, and render measurement as a visually *distinct*, irreversible, probabilistic operation — never as another tile in the gate palette. (The paper says rotations "in a Hilbert space"; the Bloch-sphere rendering is a standard design inference.)

### 5.4 The Interaction Gold Standard: Quirk

Quirk (Apache-2.0, fully in-browser, built explicitly as a learning tool) is the verified gold standard for *how* the site should feel, all points **[Demonstrated]** (3–0, five merged claims) [4][5]:

- **No run button.** "Quirk has no evaluate-the-circuit-now button. Quirk is always evaluating the circuit; it's part of the drawing code." Editing *is* simulating.
- **Sub-0.1 s feedback.** Gidney explicitly targets Nielsen's 0.1 s instantaneousness threshold, citing Bret Victor's direct-manipulation work. It is "the immediate feedback from that experimentation" that "turns into intuition."
- **The anti-example is documented too.** Gidney criticized 2016-era IBM Quantum Experience for multi-click workflows "flirting with the 10 second bucket" (verifier-corrected from "exceeding 10 seconds": a ~5 s spinner plus multi-click flow) — latency that breaks the learner's experimentation loop.
- **Inline displays.** Bloch, amplitude, and probability/sample displays embed *inside* the circuit at the point of interest — per the Quirk wiki, "a big part of using Quirk effectively amounts to putting the right kind of display in the right place."
- **URL-encoded shareable circuits.** Every circuit state is bookmarkable via URL fragment — teachers link directly to a prepared state; learners share discoveries.

Caveat: Quirk's last release is v2.3 (2019) — live and functional at algassert.com/quirk, but a pattern source, not a dependency. **[Demonstrated]** [5].

---

## 6. Recommended Architecture and Component Plan

**This entire section is [Theoretical]** — a synthesis derived from the 3–0 findings above (vote: synthesis; the plan as a unit is inference, not an independently verified claim).

**Stack:** Next.js App Router on Vercel; all 3D in `'use client'` components; R3F v9 + drei on React 19 (v8 on React 18, per §3.2); react-three-next's persistent-Canvas + drei `<View>`/`gl.scissor` pattern so one WebGL context serves every demo (§3.1); the §4.3 hand-rolled TS statevector as the engine, re-simulating the full circuit on every interaction (15 ms-class costs make memoization unnecessary).

### 6.1 The Four Components

| # | Component | What it teaches | Design (research basis) |
|---|---|---|---|
| 1 | **Bloch-sphere hero** | Qubit state, gates as rotations, phase | H/X/Z animate as smooth reversible rotations of the state vector (counters the gates-as-collapse misconception, §5.3); synced flat circle-notation panel — amplitude as circle size, phase as hue — so the display passes the Minus-Sign Test (§5.1) and covers the categories experts rated the sphere weak on (§5.2) |
| 2 | **Gate playground** | Circuits, superposition, interference | Quirk-style drag-and-drop: no run button, continuous re-simulation under 0.1 s, inline probability + Circle Notation displays at every column, URL-encoded shareable circuits (§5.4); H·H visibly interferes back to \|0⟩ |
| 3 | **2-qubit product-vs-entangled demo** | Entanglement is *not* just superposition | Side-by-side: factorable (\|00⟩+\|01⟩)/√2 vs Bell state (§5.3 tutorial pattern, ~50%→~80%); non-Bloch primary representation, with per-qubit Bloch spheres shown *visibly degenerating* (vector shrinking toward the ball's center) as entanglement grows — turning the sphere's structural limitation (§5.2) into the lesson itself; measure one qubit, watch correlations |
| 4 | **Measurement-collapse demo** | Measurement is irreversible and probabilistic | Seeded pseudo-random shots for reproducible classroom runs; animated collapse visually unlike any gate animation; accumulating histogram of outcomes connects single-shot randomness to Born-rule statistics |

### 6.2 Anti-Patterns to Exclude

Each traceable to §5; these are the verified failure modes, stated as build-time prohibitions:

- spinning-coin / "0 and 1 at once" superposition imagery without phase (§5.1);
- "in 2^N states at once" copy without immediately unpacking amplitudes and measurement (§5.3);
- measurement rendered as a gate tile visually indistinguishable from unitaries (§5.3);
- the Bloch sphere as the sole representation for anything multi-qubit (§5.2).

### 6.3 Mobile, Performance, Accessibility

- **One canvas, many views:** single shared WebGL context with `<View>` portals — the verified ~79 kB pattern [1]; avoids the multi-context cost of one canvas per demo.
- **`frameloop="demand"`:** static scenes render zero frames between interactions; animation loops run only during gate animations and collapse sequences.
- **Touch-first:** interactions follow Q.js's verified precedent of paired mouse/touch handlers (`mousedown`/`touchstart`, `mousemove`/`touchmove`, `mouseup`/`touchend`, reading `event.changedTouches`) so the gate playground works identically on mobile **[Demonstrated]** precedent (3–0) [8][9].
- **Reduced motion:** honor `prefers-reduced-motion` with a static 2D circle-notation fallback that *preserves the phase information* rather than dropping it — degrading the rendering, not the physics.
- **Accessibility, flagged honestly:** no a11y claims survived verification (§2 coverage gaps), so keyboard-operable gate placement and `aria-live` state descriptions are design intentions to be validated during the build, not research-backed patterns. **[Theoretical]** throughout this subsection.

---

## 7. Reusable Open-Source Building Blocks

All licenses verified live against repositories/npm by the verification harness (June 2026), **[Demonstrated]** (3–0) [1][3][5][9][12][13]:

| Project | License | Status (verified) | Use as |
|---|---|---|---|
| Quirk [5] | Apache-2.0 | Live; last release v2.3 (2019) | Interaction gold standard; WebGL simulation engine patterns |
| quantum-circuit (npm) [3] | MIT | **Active** — 0.9.247, 2026-02-09 | Ready-made engine fallback; sparse statevector-as-map pattern |
| Q.js [8][9] | MIT (repo LICENSE.md; site names no license) | Dormant — last push 2023-04 | Touch-capable drag-and-drop editor patterns |
| react-three-next [1] | MIT | Dormant — last push 2024-06, pins Next 14 / R3F v8 | Persistent-Canvas + View architecture pattern |
| Quantum Tensors [12] | MIT (npm 0.4.15) | Last published 2022 | In-browser quantum-info processing reference (qudits, POVMs, sparse tensor algebra) |
| BraKetVue [13] | MIT (npm 0.4.3) | Last published 2022; **Vue.js** | The amplitude-as-circle-size, phase-as-hue rendering idiom — exactly the encoding the Minus-Sign Test demands. Port the idiom, not the code |

Notes:

- The maintenance picture is uniform and should be stated plainly: **only quantum-circuit is currently maintained.** Everything else is pattern and reference material — which is fine, because Section 6 builds from patterns, not dependencies.
- BraKetVue's figure captions confirm the encoding directly ("radius for the amplitude ... hue for the phase") and the library "allows to create interactive quantum explorable explanations" [6][13]; being Vue and unpublished since 2022, it is a design reference for the React circle-notation panels, not a drop-in.
- Q.js's touch support was verified at code level (`Q/Q-Circuit-Editor.js`), and its MIT license via the raw LICENSE.md — the project site itself names no license [8][9].

---

## 8. Conclusion

The question this study set out to answer — can an experienced React/Next.js developer build a genuinely educational 3D quantum explainer in the browser — closes affirmatively on every axis checked. The architecture is a documented official pattern with verified version constraints; the simulation workload is two orders of magnitude inside verified browser limits, with a benchmarked off-the-shelf engine *and* an in-repo, 228-test-validated porting source; the licenses of every reusable building block are confirmed permissive; and — unusually for an education project — the pedagogy is not taste but published research: which representation for which concept, which misconceptions to counter with which contrast, and an interaction model (continuous evaluation, sub-0.1 s, inline displays, shareable URLs) verified against its primary sources. What remains is design execution: building the four components well, validating the accessibility intentions that research did not cover, and resisting the verified anti-patterns under copywriting pressure.

### 8.1 Open Questions

Carried forward from the verification run; refinements, not blockers:

1. Is three.js's `WebGPURenderer` (and TSL node materials) production-ready with R3F v9 in mid-2026 — and does WebGPU offer any practical benefit over WebGL for scenes this small, or is WebGL still the safe default with broader device coverage?
2. Does the react-three-next persistent-canvas + drei View pattern work unchanged on Next.js 15/16 with React 19 and Turbopack (the starter pins Next 14 / R3F v8, with open issues requesting upgrades) — and is `transpilePackages: ['three']` needed at all (§3.4)?
3. What are current best practices for making a WebGL-based educational experience accessible (keyboard-operable gate placement, `aria-live` state descriptions, `prefers-reduced-motion` fallbacks, low-end mobile GPU degradation)? No claims on this survived verification.
4. Do the flat representations experts rated highest (Circle Notation, Qake) actually produce better *learning outcomes* than the Bloch sphere in controlled studies with complete beginners, given the 2025 follow-up found no outcome difference between Bloch sphere and Quantum Bead (§5.2)?

### 8.2 Verdict

**Readiness Score: 8/10** — all infrastructure claims verified 3–0 against live sources; simulation feasibility is overdetermined (three independent performance bounds, each with ~100× headroom at 2 qubits); the test oracle already exists in this repository; the pedagogy is constrained by peer-reviewed research rather than invented. The two withheld points are honest: the pedagogy research bounds design but cannot guarantee learning outcomes (expert ratings ≠ measured learner gains, §5.2), and the accessibility and Next 15/16-portability gaps were not closed by verification (§8.1). Nothing here waits on hardware, theory, or a third party — this is the first project in this series whose bottleneck is simply doing the work.

---

## 9. References

1. pmndrs, react-three-next — official Next.js + react-three-fiber starter (persistent Canvas, drei View/gl.scissor, tunnel-rat; MIT). https://github.com/pmndrs/react-three-next
2. React Three Fiber documentation, "Installation" (R3F v8 ↔ React 18 / v9 ↔ React 19 pairing; npm peerDependencies verified June 2026). https://r3f.docs.pmnd.rs/getting-started/installation
3. Quantastica, quantum-circuit — quantum circuit simulator for JavaScript (MIT; 0.9.247, 2026-02-09; sparse statevector map; 15 ms 2-qubit benchmark). https://github.com/quantastica/quantum-circuit
4. C. Gidney, "Quirk: A Drag-and-Drop Quantum Circuit Simulator," algassert.com blog (2016) — 7-qubit pure-JS wall, ~100× WebGL speedup, no-run-button principle, 0.1 s feedback target (Nielsen / Bret Victor). https://algassert.com/2016/05/22/quirk.html
5. C. Gidney (Strilanc), Quirk — drag-and-drop quantum circuit simulator (Apache-2.0; up to 16 qubits; last release v2.3, 2019; live at algassert.com/quirk). https://github.com/Strilanc/Quirk
6. Z. C. Seskir et al., "Quantum games and interactive tools for quantum technologies outreach and education," Optical Engineering 61(8), 081809 (2022). arXiv:2202.07756 — Minus-Sign Test discussion; Quantum Flytrap Rust/WASM engine. https://arxiv.org/abs/2202.07756
7. S. Aaronson, blog post introducing the Minus-Sign Test for quantum popularizations (2011), Shtetl-Optimized. https://scottaaronson.blog/?p=613
8. Q.js — quantum circuit simulator, drag-and-drop editor, and JavaScript library, project site and documentation. https://quantumjavascript.app/
9. S. Witt (stewdio), q.js source repository (MIT via LICENSE.md; paired mouse/touch handlers in Q-Circuit-Editor.js; last push 2023-04). https://github.com/stewdio/q.js
10. Qerimi et al., expert-rating study of qubit visualizations for beginner instruction (21 experts, 16 criteria; Circle Notation 4.02±1.07, Qake 3.88±1.05, Bloch sphere best on relative phase 4.56±0.76), EPJ Quantum Technology (2025). arXiv:2409.17197. https://arxiv.org/pdf/2409.17197 — 2025 follow-up on learning outcomes: arXiv:2507.21721.
11. P. Hu, Y. Li, C. Singh, study of introductory students' misconceptions in quantum information science (superposition ≠ entanglement tutorial ~50%→~80%; 2^N reasoning primitive; non-unitary "measurement gates"), Phys. Rev. Phys. Educ. Res. 20, 020108 (2024). DOI: 10.1103/PhysRevPhysEducRes.20.020108. https://journals.aps.org/prper/abstract/10.1103/PhysRevPhysEducRes.20.020108 (preprint: arXiv:2408.04859)
12. Quantum Flytrap, quantum-tensors — in-browser quantum information processing library (MIT; npm 0.4.15; qudits, POVMs, sparse tensor algebra). https://github.com/Quantum-Flytrap/quantum-tensors
13. Quantum Flytrap, bra-ket-vue — quantum state/operator visualizer, amplitude as circle radius, phase as hue (MIT; npm 0.4.3; Vue.js, last published 2022). https://github.com/Quantum-Flytrap/bra-ket-vue
