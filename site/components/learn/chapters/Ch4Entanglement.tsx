"use client";

import { useState } from "react";
import {
  GATES1,
  applyCNOT,
  applyGate1,
  concurrence,
  reducedBloch,
  zero,
  type StateVector,
} from "@/lib/quantum/engine";
import BlochView from "@/components/three/BlochView";
import { CircleNotation } from "@/components/learn/CircleNotation";
import { Callout } from "@/components/learn/Callout";

/**
 * Chapter 4 — "Entanglement is what the sphere can't show"
 * (EXPLAINER-DESIGN §6; research doc 04 §5.2/§5.3).
 *
 * Two FIXED side-by-side panels, no free editing:
 *   left  — product state (|00⟩+|01⟩)/√2, circuit H0:  both reduced Bloch
 *           arrows keep full length r = 1 (each qubit owns a direction);
 *   right — Bell state (|00⟩+|11⟩)/√2, circuit H0·CX01: both arrows
 *           degenerate to dots at the center (r ≈ 0) — the sphere's
 *           structural silence on entanglement IS the lesson.
 *
 * The circle rows look nearly identical (two equal discs each) while the
 * spheres tell two different stories — the identical-circles-different-
 * reality framing. Concurrence quantifies it: 0.00 vs 1.00.
 *
 * Counters the Hu/Li/Singh 2024 misconception "any 2-qubit superposition
 * is entangled" — the contrast that raised correct classification from
 * ~50% to ~80%. The TRY-IT callout deep-links the Bell circuit into the
 * chapter 3 playground via the shared hash grammar (#c=H0.CX01).
 */

const BASIS_LABELS = ["|00⟩", "|01⟩", "|10⟩", "|11⟩"];

/** Fixed states, computed once from the engine (little-endian: H0 acts on
 *  qubit 0, the RIGHTMOST ket character). */
const PRODUCT: StateVector = applyGate1(zero(2), GATES1.H, 0);
const BELL: StateVector = applyCNOT(PRODUCT, 0, 1);

const BELL_HASH = "#c=H0.CX01";

function StatePanel({
  tag,
  tagTone,
  ket,
  circuit,
  state,
  framing,
}: {
  tag: string;
  tagTone: string;
  ket: string;
  circuit: string;
  state: StateVector;
  framing: string;
}) {
  const b0 = reducedBloch(state, 0);
  const b1 = reducedBloch(state, 1);
  const conc = concurrence(state);
  return (
    <div className="min-w-0 border border-white/8 bg-white/[0.02] p-5 sm:p-6">
      <p className={`font-mono text-[11px] tracking-[0.18em] ${tagTone}`}>
        {tag}
      </p>
      <p className="mt-2 font-serif text-[22px] text-paper">{ket}</p>
      <p className="mt-1 font-mono text-[12px] text-muted">
        circuit: {circuit}
      </p>
      <div className="mt-5">
        <CircleNotation amps={state.amps} labels={BASIS_LABELS} size={56} />
      </div>
      <p className="mt-3 font-mono text-[11px] leading-relaxed text-muted">
        {framing}
      </p>
      <div className="mt-6 flex flex-wrap gap-5">
        <BlochView
          bloch={b0}
          size={150}
          label={`qubit 0 · r = ${b0.r.toFixed(2)}`}
        />
        <BlochView
          bloch={b1}
          size={150}
          label={`qubit 1 · r = ${b1.r.toFixed(2)}`}
        />
      </div>
      <p className="mt-5 font-mono text-[12px] text-muted">
        entanglement (concurrence):{" "}
        <span className={conc > 0.01 ? "text-cryo" : "text-paper/85"}>
          {conc.toFixed(2)}
        </span>
      </p>
    </div>
  );
}

export default function Ch4Entanglement() {
  const [announcement, setAnnouncement] = useState("");

  // Don't preventDefault: the hash change itself is what loads the circuit
  // into Ch3 (its hashchange listener). If the hash is already the Bell
  // circuit, no hashchange would fire — dispatch one manually.
  const loadBell = () => {
    document.getElementById("ch3")?.scrollIntoView();
    if (window.location.hash === BELL_HASH) {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    }
    setAnnouncement("Loaded the Bell circuit into the chapter 3 playground.");
  };

  return (
    <section id="ch4" className="hairline scroll-mt-16">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <p className="font-mono text-[13px] text-cryo">04</p>
        <h2 className="mt-2 font-serif text-3xl text-paper sm:text-4xl">
          Entanglement is what the sphere can’t show
        </h2>

        <div className="mt-6 max-w-prose space-y-4 text-[15px] leading-relaxed text-paper/70">
          <p>
            Both panels show a two-qubit superposition with two equal
            amplitudes. On paper they look almost identical. They are not.
            The left state <em>factors</em> — qubit 1 is simply |0⟩, doing
            its own thing. The right state cannot be split into ‘qubit 0’s
            state’ and ‘qubit 1’s state’ at all. That unsplittability{" "}
            <strong className="font-medium text-paper">is</strong>{" "}
            entanglement.
          </p>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <StatePanel
            tag="PRODUCT STATE — FACTORABLE"
            tagTone="text-muted"
            ket="(|00⟩+|01⟩)/√2"
            circuit="H0"
            state={PRODUCT}
            framing="two equal discs · factors as (qubit 1 = |0⟩) × (qubit 0 = |0⟩+|1⟩)"
          />
          <StatePanel
            tag="BELL STATE — ENTANGLED"
            tagTone="text-cryo"
            ket="(|00⟩+|11⟩)/√2"
            circuit="H0 · CX01"
            state={BELL}
            framing="two equal discs · cannot be written as (qubit 1 state) × (qubit 0 state)"
          />
        </div>

        <div className="mt-10 max-w-prose space-y-4 text-[15px] leading-relaxed text-paper/70">
          <p>
            Look at the spheres. On the left, each qubit still owns a
            full-length arrow. On the right, both arrows have{" "}
            <strong className="font-medium text-paper">
              collapsed to dots at the center
            </strong>{" "}
            — each qubit alone has <em>no direction</em>, maximum
            uncertainty, even though the pair together is in a perfectly
            definite state. The Bloch sphere isn’t broken; it’s telling the
            truth: the information no longer lives in the parts.
          </p>
          <p>
            The number that quantifies this is concurrence: 0 for any product
            state, 1 for a Bell pair.
          </p>
        </div>

        <div className="mt-10 space-y-6">
          <Callout kind="misconception" title="Superposition ≠ entanglement">
            <p>
              It’s the most common error in the literature on learners:
              assuming any multi-qubit superposition is entangled.
              (|00⟩+|01⟩)/√2 is a superposition and is <em>not</em>{" "}
              entangled — it factors. In a published physics-education study, working
              through exactly this contrast raised students’
              correct-classification rate from roughly 50% to 80% (Hu, Li
              &amp; Singh 2024). You just did the same exercise.
            </p>
          </Callout>

          <Callout kind="try" title="Build the Bell state yourself">
            <p>
              <a
                href={BELL_HASH}
                onClick={loadBell}
                aria-label="Load the Bell circuit H0, CNOT01 into the chapter 3 playground"
                className="text-proven underline decoration-proven/40 underline-offset-4 transition-colors hover:decoration-proven"
              >
                Load H0 · CX01 into the chapter 3 playground
              </a>{" "}
              and watch both arrows fall to the center as the CNOT lands —
              then UNDO it and watch them grow back. Entangling is a rotation
              too: smooth, reversible, no collapse.
            </p>
          </Callout>
        </div>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>
      </div>
    </section>
  );
}
