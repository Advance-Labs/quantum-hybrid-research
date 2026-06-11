"use client";

import { useEffect, useRef, useState } from "react";
import { cAbs, cPhase, type Complex } from "@/components/bloch/qubit";
import { usePrefersReducedMotion } from "@/components/three/useReducedMotion";

/**
 * Circle notation — the workhorse flat representation (research doc 04 §5.2:
 * rated 4.02/5 by the 21-expert study, above the Bloch sphere, for
 * superposition/probability). Generalizes the landing hero's AmpChip to n
 * amplitudes: per basis state an SVG with
 *   - outer hairline circle (the unit of amplitude),
 *   - filled disc, radius ∝ |amp|, fill hsl(phaseDeg 80% 65% / 0.85),
 *   - thin phase needle from the center at the phase angle,
 *   - mono basis label beneath.
 * Phase is always drawn (hue + needle) — the Minus-Sign Test, §5.1.
 *
 * Disc radius and needle angle tween ~400 ms cubic ease-out on state change
 * (snap under prefers-reduced-motion). aria-labels always carry the *target*
 * (true) state, never mid-tween values.
 */

const TWEEN_MS = 400;
const EPS_MAG = 0.005;

/** Phase in integer degrees, normalized to [0, 360). */
function phaseDegOf(rad: number): number {
  return Math.round(((((rad * 180) / Math.PI) % 360) + 360) % 360) % 360;
}

interface AmpDisplay {
  mag: number;
  /** Radians, unwrapped (continuous across tweens), math convention (CCW). */
  phase: number;
}

/** Tween |amp| and phase toward the target; snap when reduced motion. */
function useTweenedAmp(target: AmpDisplay, reduced: boolean): AmpDisplay {
  const [disp, setDisp] = useState<AmpDisplay>(target);
  const cur = useRef<AmpDisplay>(target);
  const raf = useRef(0);

  useEffect(() => {
    cancelAnimationFrame(raf.current);
    const from = { ...cur.current };

    // Shortest-path phase target; if the amplitude vanishes the phase is
    // meaningless — hold the needle's last heading instead of swinging to 0.
    let toPhase = from.phase;
    if (target.mag >= EPS_MAG) {
      const d = target.phase - from.phase;
      toPhase = from.phase + Math.atan2(Math.sin(d), Math.cos(d));
    }
    const to: AmpDisplay = { mag: target.mag, phase: toPhase };

    if (reduced) {
      cur.current = to;
      setDisp(to);
      return;
    }
    const start = performance.now();
    const step = () => {
      const k = Math.min(1, (performance.now() - start) / TWEEN_MS);
      const e = 1 - Math.pow(1 - k, 3); // cubic ease-out
      const next: AmpDisplay = {
        mag: from.mag + (to.mag - from.mag) * e,
        phase: from.phase + (to.phase - from.phase) * e,
      };
      cur.current = next;
      setDisp(next);
      if (k < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [target.mag, target.phase, reduced]);

  return disp;
}

function AmpCircle({
  amp,
  label,
  size,
  reduced,
}: {
  amp: Complex;
  label: string;
  size: number;
  reduced: boolean;
}) {
  const targetMag = Math.min(1, cAbs(amp));
  const targetPhase = cPhase(amp);
  const { mag, phase } = useTweenedAmp(
    { mag: targetMag, phase: targetPhase },
    reduced,
  );

  const C = size / 2;
  const R_OUT = size / 2 - 2;
  const r = Math.max(0, mag) * (R_OUT - 1);
  const hue = phaseDegOf(phase);
  const nx = C + R_OUT * Math.cos(phase);
  const ny = C - R_OUT * Math.sin(phase); // SVG y is down

  // a11y reflects the true state, not the tween.
  const ariaLabel = `${label} amplitude ${targetMag.toFixed(2)}, phase ${phaseDegOf(targetPhase)} degrees`;

  return (
    <figure className="flex flex-col items-center gap-1.5">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={ariaLabel}
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

export function CircleNotation({
  amps,
  labels,
  size = 56,
  announce = false,
}: {
  amps: Complex[];
  labels: string[];
  size?: number;
  announce?: boolean;
}) {
  const reduced = usePrefersReducedMotion();
  const n = Math.min(amps.length, labels.length);

  const summary = announce
    ? Array.from({ length: n }, (_, i) => ({ amp: amps[i], label: labels[i] }))
        .filter(({ amp }) => cAbs(amp) >= EPS_MAG)
        .map(
          ({ amp, label }) =>
            `${label} amplitude ${Math.min(1, cAbs(amp)).toFixed(2)} at ${phaseDegOf(cPhase(amp))} degrees`,
        )
        .join(", ")
    : "";

  return (
    <div
      role="group"
      aria-label="Quantum state in circle notation"
      className="flex flex-wrap items-end gap-3"
    >
      {Array.from({ length: n }, (_, i) => (
        <AmpCircle
          key={labels[i]}
          amp={amps[i]}
          label={labels[i]}
          size={size}
          reduced={reduced}
        />
      ))}
      {announce && (
        <p className="sr-only" aria-live="polite">
          {summary}
        </p>
      )}
    </div>
  );
}
