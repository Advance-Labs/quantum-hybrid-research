# site/ — quantum-hybrid-research microsite

A Next.js site presenting the [quantum-hybrid-research](https://github.com/Advance-Labs/quantum-hybrid-research) initiative: three honest feasibility studies, the QLOS v0.1 dev loop, a research index, and the epistemic-tagging methodology — fronted by a live, interactive Bloch sphere. A second route, [`/learn`](#the-learn-explainer), is a five-chapter interactive explainer teaching how a quantum computer works by direct manipulation of a real statevector.

This site is itself the build output of research document 04 ([`docs/research/04-quantum-viz-education.md`](../docs/research/04-quantum-viz-education.md)): a web-based 3D quantum visualization, readiness 8/10, the only study in the series that scored as immediately buildable.

## Stack

- **Next.js 16** (App Router) + **React 19** + **TypeScript** (strict)
- **Tailwind CSS v4** — design tokens declared in `@theme` in `app/globals.css`
- **three.js / @react-three/fiber / @react-three/drei** — the Bloch-sphere scene, loaded client-side only via `next/dynamic` (`ssr: false`) so the page itself stays a server component shell

## Run it

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
npm test         # vitest — quantum-engine suite, oracle-pinned against quantum-linux/emulator/qcpu.py
```

## Structure

```
site/
├── app/
│   ├── layout.tsx          # fonts (Instrument Serif, IBM Plex Mono/Sans), metadata, grain overlay
│   ├── globals.css         # design tokens, hairlines, hero stagger animation, reduced-motion
│   ├── page.tsx            # landing: top bar · hero · 01 verdicts · 02 QLOS · 03 index · 04 methodology · footer
│   └── learn/
│       ├── page.tsx        # /learn server shell: metadata, hero, progress rail, footer
│       ├── ChaptersIsland.tsx  # client island: next/dynamic ssr:false boundary for the chapter stack
│       └── Chapters.tsx    # one SharedCanvas wrapping the five chapters
├── lib/quantum/
│   ├── engine.ts           # 1–3 qubit statevector engine (little-endian), pure TS, zero deps
│   ├── engine.test.ts      # vitest suite — amplitudes pinned to the qcpu.py oracle to 1e-9
│   └── fixtures/           # generate_fixtures.py + oracle.json (11 reference circuits)
├── components/bloch/
│   ├── qubit.ts            # single-qubit statevector math — pure TS, zero deps, global phase pinned
│   ├── BlochScene.tsx      # r3f scene: wireframe sphere, phase-hue equator ring, slerped state arrow
│   └── BlochHero.tsx       # client island: gate buttons (H/X/Z/S), circle-notation amplitude chips, |ψ⟩ readout
├── components/three/
│   ├── SharedCanvas.tsx    # one fixed canvas, many drei <View>s (the /learn 3D architecture)
│   └── BlochView.tsx       # reusable Bloch sphere view; arrow length = reduced Bloch r
└── components/learn/
    ├── CircleNotation.tsx · GateButton.tsx · Histogram.tsx · Callout.tsx
    └── chapters/           # Ch1Qubit · Ch2Interference · Ch3Playground · Ch4Entanglement · Ch5Measurement
```

## The /learn explainer

`/learn` implements research document 04's component plan (§6) and pedagogy rules (§5) as a five-chapter scrolled narrative: **01** a qubit is an arrow (gates are rotations, never collapses) · **02** interference — the minus sign made visible · **03** a 2-qubit circuit playground with URL-shareable circuits (`#c=H0.CX01`, Quirk-style: no run button, every edit re-simulates instantly) · **04** entanglement as the Bloch sphere's structural failure (reduced arrows shrink to dots for a Bell pair) · **05** measurement, the page's only snap.

The statevector engine (`lib/quantum/engine.ts`) is oracle-tested: `lib/quantum/fixtures/generate_fixtures.py` runs the same circuits through the repository's 72-test Python emulator (`quantum-linux/emulator/qcpu.py`) and the vitest suite (`npm test`) pins the TypeScript amplitudes to that output at 1e-9. Phase is drawn on every state (hue + needle — the Minus-Sign Test); explicit MISCONCEPTION callouts counter the three documented learner errors (Hu/Li/Singh 2024); all 3D renders through a single shared canvas (drei `View`), loaded client-side only.

## The Bloch hero

The hero is a real statevector, not an animation. `qubit.ts` holds |ψ⟩ = α|0⟩ + β|1⟩ as complex amplitudes; gate buttons apply the actual 2×2 unitaries and the arrow slerps to the new (θ, φ). Design choices follow the pedagogy findings of research doc 04:

- **Phase is visible** (Aaronson's Minus-Sign Test): the equator ring is hue-mapped to azimuth, and circle-notation chips show each amplitude's magnitude (filled radius) and phase (hue + needle).
- **No run button** (the Quirk standard): every gate press gives sub-100 ms feedback.
- **Global phase is pinned** (α real, non-negative) so the displayed amplitudes are deterministic.
- **`prefers-reduced-motion`** disables the autorotate and snaps state changes instead of easing; the hero text stagger collapses to plain visibility.

## Design system

| Token | Value | Role |
|---|---|---|
| `ink` | `#08090c` | background |
| `paper` | `#e9e7e0` | foreground |
| `muted` | `#8a8f98` | secondary text |
| `cryo` | `#7dedff` | accent / [Demonstrated] |
| `proven` | `#4ade80` | [Proven] |
| `theory` | `#fbbf24` | [Theoretical] |
| `spec` | `#f87171` | [Speculative] |

Type: Instrument Serif for headlines, IBM Plex Mono for labels/code/data, IBM Plex Sans for body. One structural line weight (`.hairline`, 9% paper) everywhere; a ~3% SVG `feTurbulence` grain overlay sits above the page.

All GitHub links on the page point at files that exist in this repository; the readiness scores, loss curves, test counts, and verdicts are quoted from the research documents, not paraphrased upward.
