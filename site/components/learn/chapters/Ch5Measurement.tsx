"use client";

import { useRef, useState } from "react";
import BlochView from "@/components/three/BlochView";
import { Callout } from "@/components/learn/Callout";
import { CircleNotation } from "@/components/learn/CircleNotation";
import { GateButton } from "@/components/learn/GateButton";
import { Histogram } from "@/components/learn/Histogram";
import {
  GATES1,
  applyGate1,
  ketString,
  measureQubit,
  mulberry32,
  probabilities,
  reducedBloch,
  zero,
  type StateVector,
} from "@/lib/quantum/engine";

/**
 * Chapter 05 — "Measurement is the only collapse" (EXPLAINER-DESIGN §6, Ch5).
 *
 * One qubit: PREPARE (|0⟩ pole / H equator) → MEASURE → seeded-shot
 * histogram (Born rule). Preparation is a gate, so it TWEENS like every
 * other rotation on the page; measurement is THE page's only snap —
 * implemented by remounting BlochView + CircleNotation via a key bump, which
 * both components render without an entry tween on first paint. The visual
 * grammar (gates turn / measurement snaps) IS the physics (research doc 04
 * §5.3 #3, §6.1 #4).
 *
 * RNG: mulberry32 with fixed seed 0x5eed per mount, reseeded by RESET STATS,
 * so classroom runs reproduce exactly. Must render under <SharedCanvas>.
 */

const SEED = 0x5eed;
const BASIS_LABELS = ["|0⟩", "|1⟩"];
const HIST_LABELS = ["0", "1"];

type Prep = "zero" | "plus";

const preparedState = (p: Prep): StateVector =>
  p === "zero" ? zero(1) : applyGate1(zero(1), GATES1.H, 0);

const sideButtonClass =
  "h-12 shrink-0 border border-white/15 px-4 font-mono text-[12px] tracking-wider text-muted transition-colors hover:border-cryo hover:text-cryo";

export default function Ch5Measurement() {
  const rng = useRef<() => number>(mulberry32(SEED));
  const [prep, setPrep] = useState<Prep>("plus");
  const [state, setState] = useState<StateVector>(() => preparedState("plus"));
  const [counts, setCounts] = useState<Record<string, number>>({
    "0": 0,
    "1": 0,
  });
  const [total, setTotal] = useState(0);
  /** Bumped ONLY on measurement: remount = snap, the page's only one. */
  const [snapKey, setSnapKey] = useState(0);
  const [announcement, setAnnouncement] = useState("");

  const bloch = reducedBloch(state, 0);
  const probs = probabilities(state);

  const doPrepare = (p: Prep) => {
    setPrep(p);
    const next = preparedState(p);
    setState(next); // no key bump — preparation rotates smoothly
    setAnnouncement(
      p === "zero"
        ? `Prepared |0⟩. |ψ⟩ = ${ketString(next)}`
        : `Applied H to qubit 0. |ψ⟩ = ${ketString(next)}`,
    );
  };

  const measureOnce = () => {
    const { outcome, collapsed } = measureQubit(state, 0, rng.current);
    setState(collapsed);
    setSnapKey((k) => k + 1);
    setCounts((c) => ({
      ...c,
      [String(outcome)]: (c[String(outcome)] ?? 0) + 1,
    }));
    setTotal((t) => t + 1);
    setAnnouncement(`Measured ${outcome}. State collapsed to |${outcome}⟩`);
  };

  /** 100 prepare→measure shots with the selected preparation. */
  const run100 = () => {
    let zeros = 0;
    let lastOutcome: 0 | 1 = 0;
    let lastState = state;
    for (let i = 0; i < 100; i++) {
      const { outcome, collapsed } = measureQubit(
        preparedState(prep),
        0,
        rng.current,
      );
      if (outcome === 0) zeros += 1;
      lastOutcome = outcome;
      lastState = collapsed;
    }
    setState(lastState);
    setSnapKey((k) => k + 1);
    setCounts((c) => ({
      "0": (c["0"] ?? 0) + zeros,
      "1": (c["1"] ?? 0) + (100 - zeros),
    }));
    setTotal((t) => t + 100);
    setAnnouncement(
      `Ran 100 shots: ${zeros} × 0, ${100 - zeros} × 1. Last shot measured ${lastOutcome}. State collapsed to |${lastOutcome}⟩`,
    );
  };

  const resetStats = () => {
    rng.current = mulberry32(SEED); // seed resets with the stats
    setCounts({ "0": 0, "1": 0 });
    setTotal(0);
    setAnnouncement("Statistics reset; random seed restored.");
  };

  return (
    <section id="ch5" className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-[13px] text-cryo">05</span>
          <h2 className="font-serif text-3xl text-paper sm:text-4xl">
            Measurement is the only collapse
          </h2>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
          <div className="flex min-w-0 flex-col gap-5">
            <p className="max-w-prose text-[15px] leading-relaxed text-paper/75">
              Everything until now was reversible rotation. Measurement is the
              one move that isn&rsquo;t. Ask the qubit &lsquo;are you 0 or
              1?&rsquo; and you get one classical bit — with probability given
              by the disc areas below (the{" "}
              <strong className="font-medium text-paper">Born rule</strong>:
              probability = |amplitude|²) — and the arrow snaps to the pole you
              got. The superposition is gone; measuring again returns the same
              answer.
            </p>
            <p className="max-w-prose text-[15px] leading-relaxed text-paper/75">
              Notice the visual grammar of this whole page: gates <em>turn</em>{" "}
              smoothly, measurement <em>snaps</em>. That distinction is the
              physics. A quantum computation is long careful choreography of
              rotations, ending in exactly one irreversible question.
            </p>
            <p className="max-w-prose text-[15px] leading-relaxed text-paper/75">
              Run a hundred shots on an H-prepared qubit: the histogram
              converges toward 50/50, one random bit at a time. Single outcomes
              are random; the <em>distribution</em> is exactly determined by
              the state.
            </p>
            <div className="mt-2 max-w-prose">
              <Callout kind="note" title="Why errors are so hard">
                Anything that interacts with a qubit — stray light, heat, a
                curious classical wire — acts like an accidental measurement.
                That&rsquo;s decoherence, and it&rsquo;s why the machines in
                our{" "}
                <a
                  href="https://github.com/Advance-Labs/quantum-hybrid-research/blob/main/docs/research/03-hybrid-board.md"
                  target="_blank"
                  rel="noreferrer"
                  className="text-cryo underline decoration-cryo/40 underline-offset-2 transition-colors hover:decoration-cryo"
                >
                  hardware study
                </a>{" "}
                live in dilution refrigerators.
              </Callout>
            </div>
          </div>

          <div className="flex min-w-0 flex-col gap-6">
            <div
              role="group"
              aria-label="Prepare the qubit"
              className="flex flex-wrap items-center gap-3"
            >
              <span className="font-mono text-[11px] tracking-[0.18em] text-muted">
                PREPARE
              </span>
              <GateButton
                gate="|0⟩"
                ariaLabel="Prepare the qubit in state |0⟩, the north pole"
                active={prep === "zero"}
                onClick={() => doPrepare("zero")}
              />
              <GateButton
                gate="H"
                ariaLabel="Prepare the qubit with a Hadamard gate, an equal superposition on the equator"
                active={prep === "plus"}
                onClick={() => doPrepare("plus")}
              />
            </div>

            <div className="flex min-w-0 flex-col items-center gap-5 overflow-hidden">
              <BlochView
                key={`bloch-${snapKey}`}
                bloch={bloch}
                size={240}
                label="qubit 0"
              />
              <CircleNotation
                key={`circles-${snapKey}`}
                amps={state.amps}
                labels={BASIS_LABELS}
                size={64}
              />
              <p className="font-mono text-[12px] tabular-nums text-paper/85">
                P(0) = {probs[0].toFixed(2)} · P(1) = {probs[1].toFixed(2)}
                <span className="text-muted"> — Born rule: P = |amp|²</span>
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={measureOnce}
                aria-label="Measure the qubit"
                className="h-12 min-w-44 grow border border-cryo/60 px-6 font-mono text-[13px] tracking-[0.18em] text-cryo transition-colors hover:bg-cryo/10"
              >
                MEASURE
              </button>
              <button
                type="button"
                onClick={run100}
                aria-label="Prepare and measure 100 times"
                className={sideButtonClass}
              >
                ×100
              </button>
              <button
                type="button"
                onClick={resetStats}
                aria-label="Reset measurement statistics and restore the random seed"
                className={sideButtonClass}
              >
                RESET STATS
              </button>
            </div>

            <Histogram counts={counts} total={total} labels={HIST_LABELS} />
          </div>
        </div>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>
      </div>
    </section>
  );
}
