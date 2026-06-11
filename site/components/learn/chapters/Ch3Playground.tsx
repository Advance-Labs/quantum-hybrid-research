"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  GATES1,
  applyCNOT,
  applyGate1,
  concurrence,
  ketString,
  probOfQubit,
  reducedBloch,
  zero,
  type StateVector,
} from "@/lib/quantum/engine";
import BlochView from "@/components/three/BlochView";
import { CircleNotation } from "@/components/learn/CircleNotation";
import { GateButton } from "@/components/learn/GateButton";
import { Callout } from "@/components/learn/Callout";

/**
 * Chapter 3 — "Compose your own circuit" (EXPLAINER-DESIGN §6, the
 * centerpiece). A 2-qubit tap-to-build playground:
 *
 *   - Quirk interaction model (research doc 04 §5.4): NO run button — the
 *     full statevector is recomputed from the op list on every edit.
 *   - Tap a palette gate, then tap a wire to append (CNOT: tap the CONTROL
 *     wire; the other qubit is the target, drawn as a ●—⊕ column).
 *   - URL-shareable circuits, Quirk-style hash grammar `#c=H0.X1.CX01`
 *     (tokens /^(H|X|Y|Z|S|T)[01]$/ and /^CX[01][01]$/, control ≠ target).
 *     Parsed on mount + on `hashchange` (so chapter 4's TRY-IT link works);
 *     `history.replaceState` on every edit; SHARE copies via
 *     navigator.clipboard with a prompt() fallback.
 *   - Readouts: circle notation (4 amps), two reduced Bloch spheres
 *     (arrows shrink as entanglement grows), per-qubit probability bars,
 *     and the live concurrence line.
 *
 * Qubit ordering is the engine's little-endian convention: basis labels
 * |q1 q0⟩, rightmost character = qubit 0.
 */

type GateName = "H" | "X" | "Y" | "Z" | "S" | "T";
type Armed = GateName | "CX" | null;

type Op =
  | { readonly kind: "g"; readonly gate: GateName; readonly q: 0 | 1 }
  | { readonly kind: "cx"; readonly control: 0 | 1; readonly target: 0 | 1 };

const BASIS_LABELS = ["|00⟩", "|01⟩", "|10⟩", "|11⟩"];

/** Palette offers H X Z S + CNOT; Y/T are still accepted from shared URLs. */
const PALETTE: readonly GateName[] = ["H", "X", "Z", "S"];

const GATE_WORDS: Record<GateName, string> = {
  H: "Hadamard",
  X: "Pauli-X",
  Y: "Pauli-Y",
  Z: "Pauli-Z",
  S: "S phase",
  T: "T phase",
};

const GATE_TOKEN = /^(H|X|Y|Z|S|T)([01])$/;
const CX_TOKEN = /^CX([01])([01])$/;

/** `#c=H0.X1.CX01` → ops. Invalid tokens are ignored; the rest is kept. */
function parseHash(hash: string): Op[] {
  const m = /^#c=(.+)$/.exec(hash);
  if (!m) return [];
  const ops: Op[] = [];
  for (const token of m[1].split(".")) {
    const g = GATE_TOKEN.exec(token);
    if (g) {
      ops.push({ kind: "g", gate: g[1] as GateName, q: Number(g[2]) as 0 | 1 });
      continue;
    }
    const c = CX_TOKEN.exec(token);
    if (c && c[1] !== c[2]) {
      ops.push({
        kind: "cx",
        control: Number(c[1]) as 0 | 1,
        target: Number(c[2]) as 0 | 1,
      });
    }
  }
  return ops;
}

function serialize(ops: readonly Op[]): string {
  return ops
    .map((op) =>
      op.kind === "g" ? `${op.gate}${op.q}` : `CX${op.control}${op.target}`,
    )
    .join(".");
}

/** Continuous evaluation: the state IS the circuit. ~µs for 2 qubits. */
function evalOps(ops: readonly Op[]): StateVector {
  return ops.reduce<StateVector>(
    (s, op) =>
      op.kind === "g"
        ? applyGate1(s, GATES1[op.gate], op.q)
        : applyCNOT(s, op.control, op.target),
    zero(2),
  );
}

/* ------------------------------------------------------------------ */
/* Timeline                                                            */
/* ------------------------------------------------------------------ */

/**
 * One op column on one wire row. Chips are inert spans — the whole wire
 * row is the (≥44 px) tap target. q1 is the UPPER wire, so the CNOT
 * connector runs downward from row 1 and upward from row 0.
 */
function TimelineCell({ op, row }: { op: Op; row: 0 | 1 }) {
  if (op.kind === "g") {
    if (op.q !== row) return <span className="w-12 shrink-0" aria-hidden />;
    return (
      <span
        aria-hidden
        className="flex w-12 shrink-0 items-center justify-center"
      >
        <span className="flex h-9 w-9 items-center justify-center border border-white/25 bg-ink font-mono text-[13px] text-paper">
          {op.gate}
        </span>
      </span>
    );
  }
  const isControl = op.control === row;
  const connector = row === 1 ? "top-1/2 bottom-0" : "top-0 bottom-1/2";
  return (
    <span
      aria-hidden
      className="relative flex w-12 shrink-0 items-center justify-center"
    >
      <span
        className={`absolute left-1/2 w-px -translate-x-1/2 bg-cryo/60 ${connector}`}
      />
      {isControl ? (
        <span className="relative h-2.5 w-2.5 rounded-full bg-cryo" />
      ) : (
        <span className="relative flex h-7 w-7 items-center justify-center rounded-full border border-cryo bg-ink font-mono text-[15px] leading-none text-cryo">
          +
        </span>
      )}
    </span>
  );
}

function WireRow({
  row,
  ops,
  armed,
  onTap,
}: {
  row: 0 | 1;
  ops: readonly Op[];
  armed: Armed;
  onTap: (q: 0 | 1) => void;
}) {
  const other = row === 0 ? 1 : 0;
  const ariaLabel =
    armed === null
      ? `Qubit ${row} wire. Select a gate from the palette first.`
      : armed === "CX"
        ? `Add CNOT with control qubit ${row}, target qubit ${other}`
        : `Apply ${GATE_WORDS[armed]} gate to qubit ${row}`;
  return (
    <button
      type="button"
      onClick={() => onTap(row)}
      aria-label={ariaLabel}
      className={`flex h-14 w-full min-w-max items-center text-left transition-colors ${
        armed !== null ? "hover:bg-cryo/5" : ""
      }`}
    >
      <span className="w-9 shrink-0 font-mono text-[12px] text-muted">
        q{row}
      </span>
      <span className="relative flex h-full min-w-0 flex-1 items-center pr-12">
        <span
          aria-hidden
          className="absolute left-0 right-0 top-1/2 h-px bg-white/15"
        />
        {ops.map((op, i) => (
          <TimelineCell key={i} op={op} row={row} />
        ))}
      </span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Small UI pieces                                                     */
/* ------------------------------------------------------------------ */

function ToolButton({
  label,
  onClick,
  ariaLabel,
  disabled = false,
  tone = "muted",
}: {
  label: string;
  onClick: () => void;
  ariaLabel: string;
  disabled?: boolean;
  tone?: "muted" | "cryo";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className={`h-11 border px-4 font-mono text-[12px] tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        tone === "cryo"
          ? "border-cryo/60 text-cryo enabled:hover:bg-cryo/10"
          : "border-white/15 text-muted enabled:hover:border-white/40 enabled:hover:text-paper"
      }`}
    >
      {label}
    </button>
  );
}

/** One probability bar; the mono text is the accessible carrier. */
function ProbRow({ label, p }: { label: string; p: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 font-mono text-[12px] text-muted">
        {label}
      </span>
      <span
        className="relative h-2.5 min-w-0 flex-1 overflow-hidden border border-white/8"
        aria-hidden
      >
        <span
          className="absolute inset-y-0 left-0 bg-cryo/50 transition-[width] duration-300 ease-out motion-reduce:transition-none"
          style={{ width: `${p * 100}%` }}
        />
      </span>
      <span className="w-14 shrink-0 text-right font-mono text-[12px] tabular-nums text-paper/85">
        {(p * 100).toFixed(1)}%
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Chapter                                                             */
/* ------------------------------------------------------------------ */

export default function Ch3Playground() {
  const [ops, setOps] = useState<readonly Op[]>([]);
  const [armed, setArmed] = useState<Armed>(null);
  const [announcement, setAnnouncement] = useState("");
  const [copied, setCopied] = useState(false);
  const hydrated = useRef(false);
  const copyTimer = useRef(0);

  // Load circuit from the URL on mount, and again whenever a `#c=` hash
  // arrives later (e.g. chapter 4's TRY-IT link). Plain anchor hashes
  // (#ch1…#ch5 from the progress rail) are ignored.
  useEffect(() => {
    setOps(parseHash(window.location.hash));
    hydrated.current = true;
    const onHash = () => {
      if (!window.location.hash.startsWith("#c=")) return;
      const parsed = parseHash(window.location.hash);
      setOps(parsed);
      setArmed(null);
      setAnnouncement(
        `Circuit loaded from link. |ψ⟩ = ${ketString(evalOps(parsed))}`,
      );
    };
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.clearTimeout(copyTimer.current);
    };
  }, []);

  // The address bar is the save file: replaceState on every edit.
  useEffect(() => {
    if (!hydrated.current) return;
    if (ops.length > 0) {
      history.replaceState(null, "", `#c=${serialize(ops)}`);
    } else if (window.location.hash.startsWith("#c=")) {
      history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    }
  }, [ops]);

  const state = useMemo(() => evalOps(ops), [ops]);
  const b0 = useMemo(() => reducedBloch(state, 0), [state]);
  const b1 = useMemo(() => reducedBloch(state, 1), [state]);
  const p0 = probOfQubit(state, 0);
  const p1 = probOfQubit(state, 1);
  const conc = concurrence(state);

  const place = (q: 0 | 1) => {
    if (armed === null) {
      setAnnouncement("Select a gate from the palette first, then tap a wire.");
      return;
    }
    let next: Op[];
    let action: string;
    if (armed === "CX") {
      const target: 0 | 1 = q === 0 ? 1 : 0;
      next = [...ops, { kind: "cx", control: q, target }];
      action = `Applied CNOT with control qubit ${q}, target qubit ${target}`;
    } else {
      next = [...ops, { kind: "g", gate: armed, q }];
      action = `Applied ${armed} to qubit ${q}`;
    }
    setOps(next);
    setArmed(null);
    setAnnouncement(`${action}. |ψ⟩ = ${ketString(evalOps(next))}`);
  };

  const undo = () => {
    if (ops.length === 0) return;
    const next = ops.slice(0, -1);
    setOps(next);
    setAnnouncement(
      `Removed last operation. |ψ⟩ = ${ketString(evalOps(next))}`,
    );
  };

  const clear = () => {
    setOps([]);
    setArmed(null);
    setAnnouncement("Cleared circuit. State reset to |00⟩.");
  };

  const share = async () => {
    const url = window.location.href;
    let ok = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(url);
        ok = true;
      } catch {
        ok = false;
      }
    }
    if (!ok) window.prompt("Copy this link to share your circuit:", url);
    setAnnouncement(
      ok ? "Shareable link copied to clipboard." : "Shareable link shown in prompt.",
    );
    setCopied(true);
    window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <section id="ch3" className="hairline scroll-mt-16">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <p className="font-mono text-[13px] text-cryo">03</p>
        <h2 className="mt-2 font-serif text-3xl text-paper sm:text-4xl">
          Compose your own circuit
        </h2>

        <div className="mt-6 max-w-prose space-y-4 text-[15px] leading-relaxed text-paper/70">
          <p>
            This is a real two-qubit quantum computer — simulated exactly,
            because two qubits need only four complex numbers. Build any
            circuit; everything updates as you tap. There is no run button:
            the state <em>is</em> the circuit.
          </p>
          <p>
            Try <code className="font-mono text-[13px] text-paper">H</code> on
            q0 then{" "}
            <code className="font-mono text-[13px] text-paper">CNOT</code> with
            q0 as control. Watch the two spheres while you do it — chapter 4
            explains what just happened to them.
          </p>
          <p>
            Share button copies a link to your exact circuit — the address bar
            is the save file.
          </p>
        </div>

        <div className="mt-10 border border-white/8 bg-white/[0.02] p-4 sm:p-6">
          {/* Palette + tools */}
          <div className="flex flex-wrap items-center gap-2">
            {PALETTE.map((g) => (
              <GateButton
                key={g}
                gate={g}
                active={armed === g}
                onClick={() => setArmed(armed === g ? null : g)}
                ariaLabel={`Select ${GATE_WORDS[g]} gate, then tap a wire to place it`}
              />
            ))}
            <GateButton
              gate="CNOT"
              active={armed === "CX"}
              onClick={() => setArmed(armed === "CX" ? null : "CX")}
              ariaLabel="Select CNOT, then tap the control wire — the other qubit becomes the target"
            />
            <span aria-hidden className="mx-1 hidden h-6 w-px bg-white/10 sm:block" />
            <ToolButton
              label="UNDO"
              onClick={undo}
              ariaLabel="Undo last operation"
              disabled={ops.length === 0}
            />
            <ToolButton
              label="CLEAR"
              onClick={clear}
              ariaLabel="Clear circuit"
              disabled={ops.length === 0}
            />
            <ToolButton
              label={copied ? "COPIED" : "SHARE"}
              onClick={share}
              ariaLabel="Copy shareable link"
              tone="cryo"
            />
          </div>

          <p className="mt-3 font-mono text-[11px] text-muted" aria-hidden>
            {armed === null
              ? "tap a gate, then tap a wire to place it"
              : armed === "CX"
                ? "now tap the CONTROL wire — the other qubit becomes the target"
                : `now tap a wire to place ${armed}`}
          </p>

          {/* Wires — q1 above, q0 below; scrolls horizontally, never the page */}
          <div className="mt-4 overflow-x-auto">
            <div className="w-max min-w-full">
              <WireRow row={1} ops={ops} armed={armed} onTap={place} />
              <WireRow row={0} ops={ops} armed={armed} onTap={place} />
            </div>
          </div>

          {/* Readouts */}
          <div className="mt-8 grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="min-w-0">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">
                STATE — CIRCLE NOTATION
              </p>
              <div className="mt-4">
                <CircleNotation
                  amps={state.amps}
                  labels={BASIS_LABELS}
                  size={64}
                />
              </div>
              <p className="mt-4 break-words font-mono text-[12px] text-paper/85">
                |ψ⟩ = {ketString(state)}
              </p>
              <div className="mt-6 flex flex-col gap-1.5">
                <ProbRow label="P(q0=0)" p={p0.p0} />
                <ProbRow label="P(q0=1)" p={p0.p1} />
                <ProbRow label="P(q1=0)" p={p1.p0} />
                <ProbRow label="P(q1=1)" p={p1.p1} />
              </div>
              <p className="mt-5 font-mono text-[12px] text-muted">
                entanglement (concurrence):{" "}
                <span className={conc > 0.01 ? "text-cryo" : "text-paper/85"}>
                  {conc.toFixed(2)}
                </span>
              </p>
            </div>
            <div className="min-w-0">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">
                REDUCED BLOCH SPHERES
              </p>
              <div className="mt-4 flex flex-wrap gap-6">
                <BlochView
                  bloch={b0}
                  size={180}
                  label={`qubit 0 · r = ${b0.r.toFixed(2)}`}
                />
                <BlochView
                  bloch={b1}
                  size={180}
                  label={`qubit 1 · r = ${b1.r.toFixed(2)}`}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="mt-10">
          <Callout
            kind="misconception"
            title="It doesn’t try every answer at once"
          >
            <p>
              Two qubits hold four amplitudes, n qubits hold 2ⁿ — but you
              can’t read them all out. A measurement returns just n classical
              bits. The exponential space is real; free exponential{" "}
              <em>answers</em> are not. Algorithms must use interference
              (chapter 2) to funnel probability onto the answer before you
              look — that’s why quantum speedups are rare and precious rather
              than automatic.
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
