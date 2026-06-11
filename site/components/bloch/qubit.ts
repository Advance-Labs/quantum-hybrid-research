/**
 * Single-qubit statevector math — pure TypeScript, zero dependencies.
 *
 * State: |ψ⟩ = α|0⟩ + β|1⟩ with α, β ∈ ℂ and |α|² + |β|² = 1.
 *
 * Global-phase convention: after every gate application the state is
 * renormalized and multiplied by a unit phase so that α is REAL and
 * NON-NEGATIVE. If |α| ≈ 0 (the state is at the south pole) the phase is
 * taken out of β instead. Global phase is physically unobservable; pinning
 * it makes the displayed amplitudes and circle-notation chips deterministic.
 */

export interface Complex {
  re: number;
  im: number;
}

export interface QubitState {
  alpha: Complex;
  beta: Complex;
}

export type Gate = readonly [
  readonly [Complex, Complex],
  readonly [Complex, Complex],
];

const EPS = 1e-9;

export const complex = (re: number, im = 0): Complex => ({ re, im });

export const cAdd = (a: Complex, b: Complex): Complex => ({
  re: a.re + b.re,
  im: a.im + b.im,
});

export const cMul = (a: Complex, b: Complex): Complex => ({
  re: a.re * b.re - a.im * b.im,
  im: a.re * b.im + a.im * b.re,
});

/** Magnitude |z|. */
export const cAbs = (z: Complex): number => Math.hypot(z.re, z.im);

/** Phase angle arg(z) in radians, in (−π, π]. Defined as 0 for z ≈ 0. */
export const cPhase = (z: Complex): number =>
  cAbs(z) < EPS ? 0 : Math.atan2(z.im, z.re);

const R = Math.SQRT1_2; // 1/√2

/** Hadamard: 1/√2 · [[1, 1], [1, −1]] */
export const H: Gate = [
  [complex(R), complex(R)],
  [complex(R), complex(-R)],
];

/** Pauli-X (bit flip): [[0, 1], [1, 0]] */
export const X: Gate = [
  [complex(0), complex(1)],
  [complex(1), complex(0)],
];

/** Pauli-Z (phase flip): [[1, 0], [0, −1]] */
export const Z: Gate = [
  [complex(1), complex(0)],
  [complex(0), complex(-1)],
];

/** S (phase gate, √Z): [[1, 0], [0, i]] */
export const S: Gate = [
  [complex(1), complex(0)],
  [complex(0), complex(0, 1)],
];

/** Fresh |0⟩ state. */
export const zeroState = (): QubitState => ({
  alpha: complex(1),
  beta: complex(0),
});

/**
 * Renormalize and fix global phase (α real, non-negative — see header).
 */
function canonicalize(s: QubitState): QubitState {
  const norm = Math.hypot(cAbs(s.alpha), cAbs(s.beta));
  const ref = cAbs(s.alpha) > EPS ? cPhase(s.alpha) : cPhase(s.beta);
  const rot = complex(Math.cos(-ref) / norm, Math.sin(-ref) / norm);
  return { alpha: cMul(s.alpha, rot), beta: cMul(s.beta, rot) };
}

/** Apply a 2×2 unitary to the state: |ψ'⟩ = U|ψ⟩, then canonicalize. */
export function apply(gate: Gate, s: QubitState): QubitState {
  return canonicalize({
    alpha: cAdd(cMul(gate[0][0], s.alpha), cMul(gate[0][1], s.beta)),
    beta: cAdd(cMul(gate[1][0], s.alpha), cMul(gate[1][1], s.beta)),
  });
}

/**
 * Bloch-sphere angles for a canonicalized state:
 *   θ = 2·acos(|α|)  ∈ [0, π]   (polar, from |0⟩ at the north pole)
 *   φ = arg(β) − arg(α) ∈ (−π, π]  (azimuth, |+⟩ at φ = 0)
 */
export function blochAngles(s: QubitState): { theta: number; phi: number } {
  const a = Math.min(1, Math.max(0, cAbs(s.alpha)));
  const theta = 2 * Math.acos(a);
  const phi = cAbs(s.beta) > EPS ? cPhase(s.beta) - cPhase(s.alpha) : 0;
  return { theta, phi };
}
