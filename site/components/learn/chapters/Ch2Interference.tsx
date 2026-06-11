"use client";

import { useState } from "react";
import {
  cAbs,
  cAdd,
  cMul,
  type Complex,
  type Gate,
} from "@/components/bloch/qubit";
import { Callout } from "@/components/learn/Callout";
import { CircleNotation } from "@/components/learn/CircleNotation";
import {
  GATES1,
  applyGate1,
  ketString,
  probabilities,
  zero,
  type StateVector,
} from "@/lib/quantum/engine";

/**
 * Chapter 02 — "The minus sign that makes it quantum"
 * (EXPLAINER-DESIGN §6, Ch2 — the Minus-Sign Test made visible).
 *
 * Two PRECOMPUTED step-through strips (no free play): circuit A = H,H and
 * circuit B = H,Z,H on |0⟩. Each strip shows a circle-notation column per
 * step (the active step highlighted), prev/next buttons whose current-state
 * circles tween between columns, and — at the final step — the two-path
 * decomposition of each outcome: the route via |0⟩ and the route via |1⟩
 * drawn as amplitude circles whose needles point in OPPOSITE directions
 * where they cancel. Interference is shown, not told (research doc 04 §5.1).
 *
 * All amplitudes are computed by the real engine at module load — the same
 * unitaries the rest of the page runs, not illustration data.
 */

type GateKey = "H" | "Z";

interface Step {
  label: string;
  state: StateVector;
}

interface PathBreakdown {
  /** Final basis label, "|0⟩" or "|1⟩". */
  target: string;
  /** Contribution via the |0⟩ path and via the |1⟩ path of the prior step. */
  parts: [Complex, Complex];
  sum: Complex;
  cancels: boolean;
}

interface StripDef {
  id: string;
  header: string;
  gates: readonly GateKey[];
  steps: Step[];
  paths: PathBreakdown[];
  finalLine: string;
}

const BASIS_LABELS = ["|0⟩", "|1⟩"];

function runSteps(gates: readonly GateKey[]): Step[] {
  let s = zero(1);
  const steps: Step[] = [{ label: "start |0⟩", state: s }];
  for (const g of gates) {
    s = applyGate1(s, GATES1[g], 0);
    steps.push({ label: `after ${g}`, state: s });
  }
  return steps;
}

/**
 * Decompose the final amplitudes into their two paths: the contribution to
 * final basis state b is U[b][0]·prev₀ (via |0⟩) plus U[b][1]·prev₁ (via
 * |1⟩) — where the parts have opposite phase, they cancel.
 */
function pathBreakdowns(steps: Step[], lastGate: Gate): PathBreakdown[] {
  const prev = steps[steps.length - 2].state;
  return ([0, 1] as const).map((b) => {
    const parts: [Complex, Complex] = [
      cMul(lastGate[b][0], prev.amps[0]),
      cMul(lastGate[b][1], prev.amps[1]),
    ];
    const sum = cAdd(parts[0], parts[1]);
    return { target: `|${b}⟩`, parts, sum, cancels: cAbs(sum) < 0.01 };
  });
}

function makeStrip(
  id: string,
  header: string,
  gates: readonly GateKey[],
): StripDef {
  const steps = runSteps(gates);
  const paths = pathBreakdowns(steps, GATES1[gates[gates.length - 1]]);
  const probs = probabilities(steps[steps.length - 1].state);
  const certain = probs[0] > 0.99 ? "|0⟩" : "|1⟩";
  return {
    id,
    header,
    gates,
    steps,
    paths,
    finalLine: `P(0) = ${probs[0].toFixed(2)} · P(1) = ${probs[1].toFixed(2)} — ${certain} guaranteed`,
  };
}

const STRIP_A = makeStrip("A", "CIRCUIT A — H · H", ["H", "H"]);
const STRIP_B = makeStrip("B", "CIRCUIT B — H · Z · H", ["H", "Z", "H"]);

const stepButtonClass =
  "h-11 shrink-0 border border-white/15 px-4 font-mono text-[12px] tracking-wider text-muted transition-colors enabled:hover:border-cryo enabled:hover:text-cryo disabled:cursor-not-allowed disabled:opacity-40";

function StepStrip({
  strip,
  onAnnounce,
}: {
  strip: StripDef;
  onAnnounce: (message: string) => void;
}) {
  const [active, setActive] = useState(0);
  const last = strip.steps.length - 1;
  const current = strip.steps[active].state;

  const go = (i: number) => {
    const next = Math.max(0, Math.min(last, i));
    if (next === active) return;
    setActive(next);
    const step = strip.steps[next];
    onAnnounce(
      next === 0
        ? `Circuit ${strip.id} step 1 of ${strip.steps.length}: start at |0⟩. |ψ⟩ = ${ketString(step.state)}`
        : `Circuit ${strip.id} step ${next + 1} of ${strip.steps.length}: applied ${strip.gates[next - 1]} to qubit 0. |ψ⟩ = ${ketString(step.state)}`,
    );
  };

  return (
    <div className="flex min-w-0 flex-col border border-white/8 bg-white/[0.02] p-5">
      <p className="font-mono text-[11px] tracking-[0.18em] text-muted">
        {strip.header}
      </p>

      {/* One circle-notation column per step; the active step carries the
          cryo rule, the rest dim. */}
      <div className="mt-4 flex flex-col gap-2">
        {strip.steps.map((step, i) => (
          <div
            key={i}
            aria-current={i === active ? "step" : undefined}
            className={`flex items-center gap-4 border-l-2 py-1.5 pl-4 transition-opacity duration-300 motion-reduce:transition-none ${
              i === active
                ? "border-cryo opacity-100"
                : "border-white/10 opacity-45"
            }`}
          >
            <span className="w-16 shrink-0 font-mono text-[11px] text-muted">
              {step.label}
            </span>
            <CircleNotation
              amps={step.state.amps}
              labels={BASIS_LABELS}
              size={44}
            />
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={active === 0}
          onClick={() => go(active - 1)}
          aria-label={`Circuit ${strip.id}: previous step`}
          className={stepButtonClass}
        >
          ← PREV
        </button>
        <button
          type="button"
          disabled={active === last}
          onClick={() => go(active + 1)}
          aria-label={`Circuit ${strip.id}: next step`}
          className={stepButtonClass}
        >
          NEXT →
        </button>
        <span className="font-mono text-[11px] tabular-nums text-muted">
          step {active + 1}/{strip.steps.length}
        </span>
      </div>

      {/* Current state: these circles tween (~400 ms) as you step — the
          rotation between columns, animated. */}
      <div className="mt-5 flex flex-wrap items-center gap-5">
        <CircleNotation amps={current.amps} labels={BASIS_LABELS} size={56} />
        <p className="min-w-0 font-mono text-[12px] tabular-nums text-paper/85">
          |ψ⟩ = {ketString(current)}
        </p>
      </div>

      {/* The payoff at the final step: each outcome decomposed into its two
          paths — opposite needles cancel; aligned needles add. */}
      {active === last && (
        <div className="mt-5 border-t border-white/8 pt-4">
          <p className="font-mono text-[12px] tabular-nums text-paper/85">
            {strip.finalLine}
          </p>
          <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
            {strip.paths.map((p) => (
              <div key={p.target} className="min-w-0">
                <p className="font-mono text-[11px] text-muted">
                  paths into {p.target} —{" "}
                  <span className={p.cancels ? "text-spec" : "text-proven"}>
                    {p.cancels ? "they cancel" : "they add"}
                  </span>
                </p>
                <div className="mt-2">
                  <CircleNotation
                    amps={[p.parts[0], p.parts[1], p.sum]}
                    labels={["via |0⟩", "via |1⟩", "sum"]}
                    size={40}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Ch2Interference() {
  const [announcement, setAnnouncement] = useState("");

  return (
    <section id="ch2" className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-[13px] text-cryo">02</span>
          <h2 className="font-serif text-3xl text-paper sm:text-4xl">
            The minus sign that makes it quantum
          </h2>
        </div>

        <div className="mt-10 flex max-w-prose flex-col gap-5">
          <p className="text-[15px] leading-relaxed text-paper/75">
            Run H twice. The first H splits the arrow into an equal
            superposition. The second H splits <em>each path again</em> — and
            the two routes into |1⟩ arrive with{" "}
            <strong className="font-medium text-paper">opposite phase</strong>.
            Watch their needles: they point in opposite directions. They
            cancel. You get |0⟩ back, guaranteed.
          </p>
          <p className="text-[15px] leading-relaxed text-paper/75">
            Now slip a Z between the two H&rsquo;s. Z does nothing visible — it
            only flips one sign. But that sign reroutes the cancellation: now
            the paths into |0⟩ cancel and |1⟩ is certain.{" "}
            <strong className="font-medium text-paper">
              The entire difference between the two outcomes is a minus sign.
            </strong>
          </p>
          <p className="text-[15px] leading-relaxed text-paper/75">
            This is interference — the resource quantum computers actually run
            on. An algorithm is a choreography of phases arranged so wrong
            answers cancel and right answers add.
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-8 lg:grid-cols-2">
          <StepStrip strip={STRIP_A} onAnnounce={setAnnouncement} />
          <StepStrip strip={STRIP_B} onAnnounce={setAnnouncement} />
        </div>

        <div className="mt-12 max-w-prose">
          <Callout kind="note" title="The Minus-Sign Test">
            Scott Aaronson&rsquo;s bar for any quantum explanation: if it never
            mentions interference between positive and negative amplitudes, it
            has explained nothing — &lsquo;0 and 1 at the same time&rsquo;
            describes a coin flip, not a qubit. This page passes by
            construction: phase is drawn on every state you&rsquo;ll see.
          </Callout>
        </div>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>
      </div>
    </section>
  );
}
