# site/ — quantum-hybrid-research microsite

A single-page Next.js site presenting the [quantum-hybrid-research](https://github.com/Advance-Labs/quantum-hybrid-research) initiative: three honest feasibility studies, the QLOS v0.1 dev loop, a research index, and the epistemic-tagging methodology — fronted by a live, interactive Bloch sphere.

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
```

## Structure

```
site/
├── app/
│   ├── layout.tsx          # fonts (Instrument Serif, IBM Plex Mono/Sans), metadata, grain overlay
│   ├── globals.css         # design tokens, hairlines, hero stagger animation, reduced-motion
│   └── page.tsx            # all sections: top bar · hero · 01 verdicts · 02 QLOS · 03 index · 04 methodology · footer
└── components/bloch/
    ├── qubit.ts            # single-qubit statevector math — pure TS, zero deps, global phase pinned
    ├── BlochScene.tsx      # r3f scene: wireframe sphere, phase-hue equator ring, slerped state arrow
    └── BlochHero.tsx       # client island: gate buttons (H/X/Z/S), circle-notation amplitude chips, |ψ⟩ readout
```

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
