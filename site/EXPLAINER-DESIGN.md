# EXPLAINER-DESIGN v1.0 — `/learn`: How a Quantum Computer Works

Binding design contract for the interactive quantum explainer, implementing the component plan and
pedagogy rules of [`docs/research/04-quantum-viz-education.md`](../docs/research/04-quantum-viz-education.md) (§5, §6).
Builders implement against this document; where a builder disagrees with it, this document wins.

## 1. Overview

One new route, `/learn` — a scrolled five-chapter narrative teaching a complete beginner how a
quantum computer works by direct manipulation of a **real statevector** running in the browser.
No video, no run button, no metaphors that fail the Minus-Sign Test. The landing page stays the
research showcase; `/learn` is the explainer.

Interaction model (Quirk-derived, research doc §5d): continuous evaluation — every edit
re-simulates instantly (<0.1 s); gates animate as rotations (~550 ms); only measurement snaps.

## 2. Route & file map (BINDING ownership)

| Path (under `site/`) | Owner |
|---|---|
| `lib/quantum/engine.ts`, `lib/quantum/engine.test.ts`, `lib/quantum/fixtures/` | engine builder |
| `components/three/SharedCanvas.tsx`, `components/three/BlochView.tsx` | viz builder |
| `components/learn/CircleNotation.tsx`, `GateButton.tsx`, `Histogram.tsx`, `Callout.tsx` | viz builder |
| `components/learn/chapters/Ch1Qubit.tsx`, `Ch2Interference.tsx`, `Ch5Measurement.tsx` | chapter builder D1 |
| `components/learn/chapters/Ch3Playground.tsx`, `Ch4Entanglement.tsx` | chapter builder D2 |
| `app/learn/page.tsx`; surgical edits to `app/page.tsx`, `site/README.md`, repo `README.md` | assembly agent |
| `app/icon.svg`, `app/icon.png` (32×32), `app/apple-icon.png` (180×180); delete boilerplate `favicon.ico` | icon builder |

No builder edits another's files. Existing `components/bloch/*` stays untouched (landing-page hero).

## 3. Engine API contract — `lib/quantum/engine.ts`

Imports `Complex`, `complex`, `cAdd`, `cMul`, `cAbs`, `cPhase`, and the 2×2 `Gate` type + `H/X/Z/S`
matrices from `@/components/bloch/qubit` (do **not** duplicate them). Adds `Y` and `T` locally.

**Qubit ordering: little-endian — bit `q` of the basis-state index is qubit `q`**, matching
`quantum-linux/emulator/qcpu.py`. Example (2 qubits): index 1 = binary `01` = qubit0:1, qubit1:0 = |01⟩
written as |q1 q0⟩... — display order in UI labels is `|q1 q0⟩` for 2-qubit kets: `["|00⟩","|01⟩","|10⟩","|11⟩"]`
where the **rightmost character is qubit 0**. State this in a code comment and keep UI labels consistent.

```ts
export interface StateVector { nQubits: number; amps: Complex[] }       // amps.length === 2**nQubits

export const GATES1: Record<"H" | "X" | "Y" | "Z" | "S" | "T", Gate>;   // Gate = readonly 2x2 from qubit.ts

export function zero(nQubits: number): StateVector;                      // |0...0⟩
export function applyGate1(s: StateVector, gate: Gate, target: number): StateVector;
export function applyCNOT(s: StateVector, control: number, target: number): StateVector;
export function applyCZ(s: StateVector, a: number, b: number): StateVector;
export function probabilities(s: StateVector): number[];                 // |amp|² per basis state
export function probOfQubit(s: StateVector, q: number): { p0: number; p1: number };
export function reducedBloch(s: StateVector, q: number): { x: number; y: number; z: number; r: number };
export function concurrence(s: StateVector): number;                     // 2-qubit pure states: 2|a00·a11 − a01·a10|
export function measureQubit(s: StateVector, q: number, rand: () => number): { outcome: 0 | 1; collapsed: StateVector };
export function measureAll(s: StateVector, rand: () => number): { outcome: number; bits: string; collapsed: StateVector };
export function mulberry32(seed: number): () => number;                  // deterministic PRNG
export function ampDisplay(z: Complex): { mag: number; phaseDeg: number }; // phaseDeg ∈ [0,360)
export function ketString(s: StateVector): string;                       // "0.71|00⟩ + 0.71|11⟩" style, phase as e^(i·deg°)
```

`reducedBloch` behavioral pins (sign conventions enforced by tests, consistent with
`blochAngles` in `qubit.ts`: bloch = (sinθcosφ, sinθsinφ, cosθ)):
- `zero(1)` → z=+1, r=1 · `H|0⟩` → x=+1, r≈1 · `S·H|0⟩` → y=+1, r≈1
- Bell `(|00⟩+|11⟩)/√2` → r≈0 for both qubits · product `(|00⟩+|01⟩)/√2` → r≈1 for both.

All functions pure (return new StateVector). No classes. No external deps.

## 4. Oracle testing contract

`lib/quantum/fixtures/generate_fixtures.py` — run with `/tmp/qhr-venv/bin/python`; imports
`quantum-linux/emulator/qcpu.py` (handle its ISA-YAML path resolution via `sys.path`/`chdir`),
executes the circuits below, writes `lib/quantum/fixtures/oracle.json`
(`{ name, nQubits, ops: [...], amps: [[re,im],...] }` per circuit):

1. `X0` (1q) 2. `H0` 3. `H0,S0` 4. `H0,S0,S0` 5. `H0,Z0,H0` (interference → |1⟩)
6. `H0,H0` (identity) 7. `H0,CNOT01` (Bell) 8. `X0,CNOT01` 9. `H0,H1` (2q) 10. `T0` after `H0`
11. GHZ: `H0,CNOT01,CNOT02` (3q).

`engine.test.ts` (vitest): every oracle circuit matches amplitude-wise to 1e-9 (identical matrices in
identical order ⇒ exact match expected — a global-phase-only mismatch means a convention bug: investigate,
don't normalize). Plus pure-TS tests: reducedBloch pins above; concurrence Bell=1 / product=0;
mulberry32 determinism; measureQubit collapse correctness (post-measure state renormalized, repeat
measurement of same qubit deterministic); seeded 1000-shot H-qubit distribution within 50±5%.
Engine builder installs vitest (`npm i -D vitest`, script `"test": "vitest run"`).

## 5. Viz primitives contract

### `components/three/SharedCanvas.tsx` (`'use client'`)
The one-canvas/many-views architecture (research doc §3, drei `View`):

```tsx
export default function SharedCanvas({ children, className }: { children: React.ReactNode; className?: string });
// Renders: <div ref={container} className={className}> {children}
//   <Canvas fixed inset-0 pointer-events-none, eventSource={container}, dpr=[1,2]> <View.Port /> </Canvas></div>
```

Chapters never touch `Canvas`; they embed `<BlochView>`s anywhere in the DOM under `SharedCanvas`.

### `components/three/BlochView.tsx` (`'use client'`)
```tsx
export interface BlochViewProps {
  bloch: { x: number; y: number; z: number; r: number };   // from engine.reducedBloch
  size?: number;            // square px, default 220
  label?: string;           // mono caption under the view, e.g. "qubit 0"
  autorotate?: boolean;     // default true (off under reduced motion)
  className?: string;
}
export default function BlochView(props: BlochViewProps);
```
Renders a drei `<View>` (tracking div sized `size`) reusing **BlochScene's visual vocabulary**
(read it): wireframe lat/long great circles white @10–14%, phase-hue equator ring, cyan
#7DEDFF arrow + glowing tip dot. Arrow **length = r** (entanglement degeneration: Bell ⇒ dot at
center); animate direction (quaternion slerp) and length over ~550 ms cubic ease; snap under
reduced motion. Must stay cheap enough for 6+ simultaneous instances (share geometries via
module-level constants).

### `components/learn/CircleNotation.tsx`
```tsx
export function CircleNotation({ amps, labels, size = 56, announce = false }:
  { amps: Complex[]; labels: string[]; size?: number; announce?: boolean });
```
Generalizes the landing hero's AmpChip: per amplitude an SVG — outer hairline circle, filled disc
radius ∝ |amp| with `fill: hsl(phaseDeg 80% 65% / 0.85)`, thin phase needle from center at the
phase angle, basis label beneath in mono. Radius + needle angle tween ~400 ms (snap under reduced
motion). Each circle: `aria-label="|01⟩ amplitude 0.71, phase 90 degrees"`. This is the workhorse
representation (Circle Notation beat the Bloch sphere 4.02 vs lower in the 21-expert study — research doc §5b).

### `components/learn/GateButton.tsx`
```tsx
export function GateButton({ gate, onClick, ariaLabel, active = false, disabled = false }:
  { gate: string; onClick: () => void; ariaLabel: string; active?: boolean; disabled?: boolean });
```
Square mono button ≥44px, hairline border, hover/active border-cryo (matches hero's gate buttons).

### `components/learn/Histogram.tsx`
```tsx
export function Histogram({ counts, total, labels }:
  { counts: Record<string, number>; total: number; labels: string[] });
```
Animated horizontal mono bars (width tween), count + percentage text per row (the text IS the a11y
fallback), hairline frame.

### `components/learn/Callout.tsx`
```tsx
export function Callout({ kind, title, children }:
  { kind: "misconception" | "note" | "try"; title: string; children: React.ReactNode });
```
Left-rule box: misconception = spec-red `#F87171` rule + mono tag `MISCONCEPTION`; note = cryo +
`NOTE`; try = proven-green `#4ADE80` + `TRY IT`.

## 6. Chapter specs (narrative copy is final — use verbatim)

Every chapter: `'use client'`, self-contained state via the engine, one shared
`aria-live="polite"` region per chapter announcing `"Applied H to qubit 0. |ψ⟩ = 0.71|0⟩ + 0.71|1⟩"`
(gates) / `"Measured 1. State collapsed to |1⟩"` (measurement). Section heading: mono number +
serif title. All grids `grid-cols-1` base.

### Ch1 — "A qubit is an arrow, not a coin"
Interactive: one `BlochView` (full r=1 single qubit) + GateButtons H/X/Z/S + RESET +
`CircleNotation` (2 amps) + live ket line.
Copy: ¶1 "A classical bit is a switch: 0 or 1. A qubit is an **arrow of length one** — its state is
a direction. The poles are the classical answers |0⟩ and |1⟩; everywhere else is a superposition,
a precise direction with a precise phase — not a blur, not both-at-once." ¶2 "Every quantum gate
is a **rotation** of this arrow. H swings the pole onto the equator. X flips top for bottom. Z and
S spin the arrow around the vertical axis — they change the *phase*, the hue you see on the ring.
Apply them below: the arrow never jumps, it turns." ¶3 "The two circles underneath are the same
state in flat form — **circle notation**. Disc area is how much amplitude each answer has; the
needle and hue are its phase. The sphere is beautiful but it will fail us in chapter 4 — the
circles won't."
Callout (misconception): **"Gates don't collapse the state"** — "Applying a gate does not 'look at'
the qubit and it loses nothing. Gates are reversible rotations — apply H twice and you're back
exactly where you started. Only *measurement* (chapter 5) collapses anything."

### Ch2 — "The minus sign that makes it quantum"
Interactive: two precomputed step-through strips (no free play): circuit A = `H,H`, circuit B =
`H,Z,H` on |0⟩. Each strip: CircleNotation column per step (|0⟩ → after 1st gate → after 2nd → after
3rd), a step slider or next/prev buttons animating between columns, final probability readout.
Copy: ¶1 "Run H twice. The first H splits the arrow into an equal superposition. The second H splits
*each path again* — and the two routes into |1⟩ arrive with **opposite phase**. Watch their needles:
they point in opposite directions. They cancel. You get |0⟩ back, guaranteed." ¶2 "Now slip a Z
between the two H's. Z does nothing visible — it only flips one sign. But that sign reroutes the
cancellation: now the paths into |0⟩ cancel and |1⟩ is certain. **The entire difference between the
two outcomes is a minus sign.**" ¶3 "This is interference — the resource quantum computers actually
run on. An algorithm is a choreography of phases arranged so wrong answers cancel and right answers
add."
Callout (note): **"The Minus-Sign Test"** — "Scott Aaronson's bar for any quantum explanation: if it
never mentions interference between positive and negative amplitudes, it has explained nothing —
'0 and 1 at the same time' describes a coin flip, not a qubit. This page passes by construction:
phase is drawn on every state you'll see."

### Ch3 — "Compose your own circuit" (the centerpiece)
Interactive: 2-qubit playground. Two horizontal wires (q1 above, q0 below, mono-labeled). Palette:
H X Z S (tap a gate, then tap a wire to append) + CNOT (tap CNOT, then tap the *control* wire —
target is the other; render as ●—⊕ column) + UNDO + CLEAR + SHARE (copies URL). Continuous
evaluation: full statevector recomputed from the op list on every change. Readouts: CircleNotation
(4 amps, labels |00⟩ |01⟩ |10⟩ |11⟩), two reduced `BlochView`s ("qubit 0", "qubit 1"), per-qubit
probability bars, concurrence line `entanglement (concurrence): 0.00`.
URL grammar (hash, Quirk-style): `#c=H0.X1.CX01` — dot-separated tokens; `^(H|X|Y|Z|S|T)([01])$`
single-qubit; `^CX([01])([01])$` control,target, control≠target. Parse `location.hash` in a mount
`useEffect` (invalid tokens → ignore token, keep rest); `history.replaceState` on every edit; SHARE
uses `navigator.clipboard` with prompt() fallback.
Copy: ¶1 "This is a real two-qubit quantum computer — simulated exactly, because two qubits need
only four complex numbers. Build any circuit; everything updates as you tap. There is no run
button: the state *is* the circuit." ¶2 "Try `H` on q0 then `CNOT` with q0 as control. Watch the
two spheres while you do it — chapter 4 explains what just happened to them." ¶3 "Share button
copies a link to your exact circuit — the address bar is the save file."
Callout (misconception): **"It doesn't try every answer at once"** — "Two qubits hold four
amplitudes, n qubits hold 2ⁿ — but you can't read them all out. A measurement returns just n
classical bits. The exponential space is real; free exponential *answers* are not. Algorithms must
use interference (chapter 2) to funnel probability onto the answer before you look — that's why
quantum speedups are rare and precious rather than automatic." 

### Ch4 — "Entanglement is what the sphere can't show"
Interactive: two fixed side-by-side panels (no free editing). Left "Product state
(|00⟩+|01⟩)/√2 — circuit H0": CircleNotation (4 amps) + two reduced BlochViews + concurrence 0.00.
Right "Bell state (|00⟩+|11⟩)/√2 — circuit H0·CX01": same layout, concurrence 1.00. A TRY-IT callout
links into Ch3 via `#c=H0.CX01`.
Copy: ¶1 "Both panels show a two-qubit superposition with two equal amplitudes. On paper they look
almost identical. They are not. The left state *factors* — qubit 1 is simply |0⟩, doing its own
thing. The right state cannot be split into 'qubit 0's state' and 'qubit 1's state' at all. That
unsplittability **is** entanglement." ¶2 "Look at the spheres. On the left, each qubit still owns a
full-length arrow. On the right, both arrows have **collapsed to dots at the center** — each qubit
alone has *no direction*, maximum uncertainty, even though the pair together is in a perfectly
definite state. The Bloch sphere isn't broken; it's telling the truth: the information no longer
lives in the parts." ¶3 "The number that quantifies this is concurrence: 0 for any product state,
1 for a Bell pair."
Callout (misconception): **"Superposition ≠ entanglement"** — "It's the most common error in the
literature on learners: assuming any multi-qubit superposition is entangled. (|00⟩+|01⟩)/√2 is a
superposition and is *not* entangled — it factors. In a published physics-education study, working
through exactly this contrast raised students' correct-classification rate from roughly 50% to 80%
(Hu, Li & Singh 2024). You just did the same exercise."

### Ch5 — "Measurement is the only collapse"
Interactive: one qubit, PREPARE row (|0⟩ / H — i.e. choose pole or equator), one big MEASURE button,
×100 button, RESET STATS, `BlochView` + CircleNotation + `Histogram` (counts of 0/1, total shots).
Seeded `mulberry32` RNG (fixed seed 0x5eed per mount, reset with stats) for reproducibility.
On MEASURE the arrow **snaps** to the measured pole — explicitly no tween (the page's only snap);
histogram increments; aria-live announces.
Copy: ¶1 "Everything until now was reversible rotation. Measurement is the one move that isn't.
Ask the qubit 'are you 0 or 1?' and you get one classical bit — with probability given by the disc
areas below (the **Born rule**: probability = |amplitude|²) — and the arrow snaps to the pole you
got. The superposition is gone; measuring again returns the same answer." ¶2 "Notice the visual
grammar of this whole page: gates *turn* smoothly, measurement *snaps*. That distinction is the
physics. A quantum computation is long careful choreography of rotations, ending in exactly one
irreversible question." ¶3 "Run a hundred shots on an H-prepared qubit: the histogram converges
toward 50/50, one random bit at a time. Single outcomes are random; the *distribution* is exactly
determined by the state."
Callout (note): **"Why errors are so hard"** — "Anything that interacts with a qubit — stray light,
heat, a curious classical wire — acts like an accidental measurement. That's decoherence, and it's
why the machines in our [hardware study](../docs/research/03-hybrid-board.md) live in dilution
refrigerators."

## 7. Page architecture — `app/learn/page.tsx`

Server component shell: metadata `{ title: "Learn — How a Quantum Computer Works", description: ... }`;
top bar identical pattern to landing (wordmark links `/`, right: `Research` → `/`, `GitHub ↗`).
Hero: mono kicker `INTERACTIVE — A REAL STATEVECTOR RUNS IN THIS PAGE`; serif h1
"How a quantum computer *actually* works." (italic emphasis); 2-sentence intro: everything below is
[Proven] math — unitary rotations and the Born rule — running live, no animation-faking.
Then ONE `<SharedCanvas>` (client island via dynamic ssr:false) wrapping all five chapters.
Chapters separated by hairlines, mono numbers 01–05. Sticky right-edge progress rail (desktop only,
`hidden lg:flex`): dots + mono 01–05 anchor links. Footer: back to `/`, repo link, research doc 04
link, MIT.
Perf: `frameloop="always"` is acceptable (one canvas); dpr [1,2]; geometries shared module-level.
Reduced motion: no autorotate, snap tweens (each component handles via `matchMedia`).
Mobile: single column; the playground wires scroll horizontally inside their own
`overflow-x-auto` container if needed — the PAGE never scrolls horizontally (375px scrollWidth must equal 375).

## 8. Icon spec

`app/icon.svg` — 32×32 viewBox: dark `#08090C` rounded square (rx 6, full bleed); Bloch glyph in
cryo `#7DEDFF`: outer circle r≈11 stroke 1.75; equator ellipse (rx≈11, ry≈4.2, same center) stroke 1
at 55% opacity; state arrow: line from center to ~35° upper-right (length ≈9) stroke 1.75 with a
filled tip dot r≈1.6; one phase accent dot r≈1.3 `hsl(280 80% 65%)` sitting on the equator ellipse's
left edge. No text. Legible at 16px (nothing thinner than 1px at half scale).
`app/icon.png` 32×32 and `app/apple-icon.png` 180×180 rendered from the same design (scaled strokes);
generate via macOS `qlmanage -t -s <px>` + `sips -s format png`, or a pure-Python PNG writer — **no new
npm deps**. Delete boilerplate `app/favicon.ico`. Next 16 auto-wires `app/icon.svg`/`icon.png`/`apple-icon.png`.

## 9. A11y + announcement contract

- Every interactive control: explicit `aria-label` ("Apply Hadamard gate to qubit 0", "Measure the qubit",
  "Add CNOT with control qubit 0", "Copy shareable link").
- One `aria-live="polite"` `<p class="sr-only">` per chapter; format pinned in §6 preamble.
- Keyboard: all controls are real `<button>`s — tab + enter must work everywhere.
- Hit targets ≥44×44px. Histogram/probability data always present as text, never color-only.
- `prefers-reduced-motion`: snap all tweens, disable autorotate; content identical.

## 10. Out of scope (v1)

3-qubit playground UI (engine supports n=3 for GHZ tests only), gate dragging/reordering,
Quirk-style inline circuit displays, sound, i18n, server persistence of shared circuits.
