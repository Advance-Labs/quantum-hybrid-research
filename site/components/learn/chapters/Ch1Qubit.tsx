"use client";

import { useState } from "react";
import BlochView from "@/components/three/BlochView";
import { Callout } from "@/components/learn/Callout";
import { CircleNotation } from "@/components/learn/CircleNotation";
import { GateButton } from "@/components/learn/GateButton";
import {
  GATES1,
  applyGate1,
  ketString,
  reducedBloch,
  zero,
  type StateVector,
} from "@/lib/quantum/engine";

/**
 * Chapter 01 — "A qubit is an arrow, not a coin" (EXPLAINER-DESIGN §6, Ch1).
 *
 * One full-length (r = 1) single-qubit Bloch arrow + H/X/Z/S gate buttons +
 * RESET, paired with circle notation and a live ket line. Gates are
 * ROTATIONS: every application tweens (BlochView slerp ~550 ms, circle
 * radius/needle ~400 ms) — nothing here ever snaps. Counters the
 * gates-as-collapse misconception (research doc 04 §5.3 #3).
 *
 * Continuous evaluation: every tap re-derives the state instantly — there is
 * no run button (research doc 04 §5.4). Must render under <SharedCanvas>.
 */

type GateKey = "H" | "X" | "Z" | "S";

const GATE_ORDER: readonly GateKey[] = ["H", "X", "Z", "S"];

const GATE_NAMES: Record<GateKey, string> = {
  H: "Hadamard",
  X: "Pauli-X",
  Z: "Pauli-Z",
  S: "S phase",
};

const BASIS_LABELS = ["|0⟩", "|1⟩"];

export default function Ch1Qubit() {
  const [state, setState] = useState<StateVector>(() => zero(1));
  const [announcement, setAnnouncement] = useState("");

  const bloch = reducedBloch(state, 0);

  const applyGate = (g: GateKey) => {
    const next = applyGate1(state, GATES1[g], 0);
    setState(next);
    setAnnouncement(`Applied ${g} to qubit 0. |ψ⟩ = ${ketString(next)}`);
  };

  const reset = () => {
    const next = zero(1);
    setState(next);
    setAnnouncement(`Reset to |0⟩. |ψ⟩ = ${ketString(next)}`);
  };

  return (
    <section id="ch1" className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-[13px] text-cryo">01</span>
          <h2 className="font-serif text-3xl text-paper sm:text-4xl">
            A qubit is an arrow, not a coin
          </h2>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
          <div className="flex min-w-0 flex-col gap-5">
            <p className="max-w-prose text-[15px] leading-relaxed text-paper/75">
              A classical bit is a switch: 0 or 1. A qubit is an{" "}
              <strong className="font-medium text-paper">
                arrow of length one
              </strong>{" "}
              — its state is a direction. The poles are the classical answers
              |0⟩ and |1⟩; everywhere else is a superposition, a precise
              direction with a precise phase — not a blur, not both-at-once.
            </p>
            <p className="max-w-prose text-[15px] leading-relaxed text-paper/75">
              Every quantum gate is a{" "}
              <strong className="font-medium text-paper">rotation</strong> of
              this arrow. H swings the pole onto the equator. X flips top for
              bottom. Z and S spin the arrow around the vertical axis — they
              change the <em>phase</em>, the hue you see on the ring. Apply
              them below: the arrow never jumps, it turns.
            </p>
            <p className="max-w-prose text-[15px] leading-relaxed text-paper/75">
              The two circles underneath are the same state in flat form —{" "}
              <strong className="font-medium text-paper">
                circle notation
              </strong>
              . Disc area is how much amplitude each answer has; the needle and
              hue are its phase. The sphere is beautiful but it will fail us in
              chapter 4 — the circles won&rsquo;t.
            </p>
            <div className="mt-2 max-w-prose">
              <Callout
                kind="misconception"
                title="Gates don't collapse the state"
              >
                Applying a gate does not &lsquo;look at&rsquo; the qubit and it
                loses nothing. Gates are reversible rotations — apply H twice
                and you&rsquo;re back exactly where you started. Only{" "}
                <em>measurement</em> (chapter 5) collapses anything.
              </Callout>
            </div>
          </div>

          <div className="flex min-w-0 flex-col items-center gap-6 overflow-hidden">
            <BlochView bloch={bloch} size={260} label="qubit 0" />
            <div
              role="group"
              aria-label="Single-qubit gates"
              className="flex flex-wrap items-center justify-center gap-3"
            >
              {GATE_ORDER.map((g) => (
                <GateButton
                  key={g}
                  gate={g}
                  ariaLabel={`Apply ${GATE_NAMES[g]} gate to qubit 0`}
                  onClick={() => applyGate(g)}
                />
              ))}
              <button
                type="button"
                aria-label="Reset the qubit to |0⟩"
                onClick={reset}
                className="h-11 shrink-0 border border-white/15 px-4 font-mono text-[12px] tracking-wider text-muted transition-colors hover:border-cryo hover:text-cryo"
              >
                RESET
              </button>
            </div>
            <CircleNotation amps={state.amps} labels={BASIS_LABELS} size={64} />
            <p className="font-mono text-[12.5px] tabular-nums text-paper/85">
              |ψ⟩ = {ketString(state)}
            </p>
          </div>
        </div>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>
      </div>
    </section>
  );
}
