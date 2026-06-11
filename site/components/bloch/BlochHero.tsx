"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import {
  H,
  S,
  X,
  Z,
  apply,
  blochAngles,
  cAbs,
  cPhase,
  zeroState,
  type Complex,
  type Gate,
  type QubitState,
} from "./qubit";

const BlochScene = dynamic(() => import("./BlochScene"), {
  ssr: false,
  loading: () => <div className="h-[320px] sm:h-[400px]" aria-hidden />,
});

const GATE_BUTTONS: { symbol: string; gate: Gate; aria: string }[] = [
  { symbol: "H", gate: H, aria: "Apply Hadamard gate" },
  { symbol: "X", gate: X, aria: "Apply Pauli-X gate" },
  { symbol: "Z", gate: Z, aria: "Apply Pauli-Z gate" },
  { symbol: "S", gate: S, aria: "Apply S phase gate" },
];

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Phase in integer degrees, normalized to [0, 360). */
function phaseDeg(z: Complex): number {
  return Math.round((((cPhase(z) * 180) / Math.PI) % 360 + 360) % 360) % 360;
}

/** Circle notation: |amplitude| as filled radius, phase as hue + needle. */
function AmpChip({ label, amp }: { label: string; amp: Complex }) {
  const mag = Math.min(1, cAbs(amp));
  const ph = cPhase(amp);
  const hue = phaseDeg(amp);
  const C = 22;
  const R_OUT = 20;
  const r = mag * (R_OUT - 1);
  const nx = C + R_OUT * Math.cos(ph);
  const ny = C - R_OUT * Math.sin(ph); // SVG y is down
  return (
    <figure className="flex flex-col items-center gap-1.5">
      <svg
        width={44}
        height={44}
        viewBox="0 0 44 44"
        role="img"
        aria-label={`${label} amplitude ${mag.toFixed(2)}, phase ${hue} degrees`}
      >
        <circle
          cx={C}
          cy={C}
          r={R_OUT}
          fill="none"
          stroke="rgba(233,231,224,0.18)"
          strokeWidth={1}
        />
        {mag > 0.01 && (
          <>
            <circle cx={C} cy={C} r={r} fill={`hsl(${hue} 80% 65% / 0.85)`} />
            <line
              x1={C}
              y1={C}
              x2={nx}
              y2={ny}
              stroke="rgba(233,231,224,0.55)"
              strokeWidth={1}
            />
          </>
        )}
      </svg>
      <figcaption className="font-mono text-[11px] text-muted">
        {label}
      </figcaption>
    </figure>
  );
}

function StateLine({ state }: { state: QubitState }) {
  const f = (x: number) => x.toFixed(2);
  const mag0 = cAbs(state.alpha);
  const mag1 = cAbs(state.beta);
  const deg1 = phaseDeg(state.beta);
  return (
    <p className="font-mono text-[13px] leading-relaxed text-paper/90">
      <span className="text-muted">|ψ⟩ = </span>
      {mag0 > 0.005 && <span>{f(mag0)}|0⟩</span>}
      {mag0 > 0.005 && mag1 > 0.005 && <span className="text-muted"> + </span>}
      {mag1 > 0.005 && (
        <span>
          {f(mag1)}
          {deg1 !== 0 && (
            <>
              ·e
              <sup>i·{deg1}°</sup>
            </>
          )}
          |1⟩
        </span>
      )}
    </p>
  );
}

export default function BlochHero() {
  const [state, setState] = useState<QubitState>(zeroState);
  const reducedMotion = usePrefersReducedMotion();
  const { theta, phi } = blochAngles(state);

  return (
    <div className="border border-white/8 bg-white/[0.02]">
      <div className="h-[320px] overflow-hidden sm:h-[400px]">
        <BlochScene theta={theta} phi={phi} reducedMotion={reducedMotion} />
      </div>
      <div className="border-t border-white/8 p-5">
        <StateLine state={state} />
        <div className="mt-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
          <div className="flex gap-4">
            <AmpChip label="|0⟩" amp={state.alpha} />
            <AmpChip label="|1⟩" amp={state.beta} />
          </div>
          <div className="flex gap-2" role="group" aria-label="Quantum gates">
            {GATE_BUTTONS.map(({ symbol, gate, aria }) => (
              <button
                key={symbol}
                type="button"
                aria-label={aria}
                onClick={() => setState((s) => apply(gate, s))}
                className="h-9 w-9 border border-white/15 font-mono text-[13px] text-paper transition-colors hover:border-cryo hover:text-cryo"
              >
                {symbol}
              </button>
            ))}
            <button
              type="button"
              aria-label="Reset to the |0⟩ state"
              onClick={() => setState(zeroState())}
              className="h-9 border border-white/15 px-3 font-mono text-[11px] tracking-wider text-muted transition-colors hover:border-cryo hover:text-cryo"
            >
              RESET
            </button>
          </div>
        </div>
        <p className="mt-5 font-mono text-[11px] text-muted">
          A real statevector — gates are rotations, not collapses.
        </p>
      </div>
    </div>
  );
}
