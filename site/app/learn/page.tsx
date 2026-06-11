import type { Metadata } from "next";
import Link from "next/link";
import ChaptersIsland from "./ChaptersIsland";

/**
 * /learn — "How a quantum computer actually works" (EXPLAINER-DESIGN §7).
 *
 * Server-component shell: metadata, top bar, hero, sticky progress rail,
 * and footer render on the server; the five chapters mount client-side
 * under one SharedCanvas via ChaptersIsland (dynamic ssr:false).
 */

const REPO = "https://github.com/Advance-Labs/quantum-hybrid-research";
const RESEARCH_DOC = `${REPO}/blob/main/docs/research/04-quantum-viz-education.md`;

export const metadata: Metadata = {
  title: "Learn — How a Quantum Computer Works",
  description:
    "An interactive five-chapter explainer — qubits, interference, circuits, entanglement, measurement — driven by a real statevector running live in your browser. Proven math, directly manipulable.",
};

const CHAPTERS = [
  { id: "ch1", n: "01", title: "A qubit is an arrow, not a coin" },
  { id: "ch2", n: "02", title: "The minus sign that makes it quantum" },
  { id: "ch3", n: "03", title: "Compose your own circuit" },
  { id: "ch4", n: "04", title: "Entanglement is what the sphere can't show" },
  { id: "ch5", n: "05", title: "Measurement is the only collapse" },
] as const;

function ExtLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60"
    >
      {children}
    </a>
  );
}

/* --------------------------------------------------------------- top bar */

function TopBar() {
  return (
    <header className="border-b border-white/8">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link
          href="/"
          className="font-mono text-[12px] tracking-[0.18em] text-paper transition-colors hover:text-cryo"
        >
          QUANTUM-HYBRID RESEARCH
        </Link>
        <nav className="flex items-center gap-6 font-mono text-[12px] text-muted">
          <Link href="/" className="transition-colors hover:text-cryo">
            Research
          </Link>
          <a
            href={REPO}
            target="_blank"
            rel="noopener noreferrer"
            className="border border-white/15 px-3 py-1.5 text-paper transition-colors hover:border-cryo hover:text-cryo"
          >
            GitHub ↗
          </a>
        </nav>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ hero */

function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-6 pb-16 pt-16 sm:pt-24">
      <p className="rise font-mono text-[12px] tracking-[0.18em] text-muted">
        INTERACTIVE — A REAL STATEVECTOR RUNS IN THIS PAGE
      </p>
      <h1
        className="rise mt-6 max-w-3xl font-serif text-5xl leading-[1.05] text-paper sm:text-6xl"
        style={{ animationDelay: "90ms" }}
      >
        How a quantum computer <em className="text-cryo">actually</em> works.
      </h1>
      <p
        className="rise mt-6 max-w-2xl text-[15px] leading-relaxed text-muted"
        style={{ animationDelay: "180ms" }}
      >
        Everything below is{" "}
        <span className="font-mono text-[12px] text-proven">[Proven]</span>{" "}
        math — unitary rotations and the Born rule — running live in your
        browser as a real statevector you manipulate directly. Nothing is an
        animation faking the physics: the figures don&apos;t illustrate the
        state, they are computed from it on every tap.
      </p>
      <nav
        aria-label="Chapter contents"
        className="rise mt-10 max-w-2xl border border-white/8"
        style={{ animationDelay: "270ms" }}
      >
        <ul>
          {CHAPTERS.map((c) => (
            <li key={c.id} className="border-b border-white/8 last:border-b-0">
              <a
                href={`#${c.id}`}
                className="flex min-h-11 items-baseline gap-4 px-5 py-3 transition-colors hover:bg-white/[0.03]"
              >
                <span className="font-mono text-[12px] text-cryo">{c.n}</span>
                <span className="font-serif text-lg text-paper">{c.title}</span>
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </section>
  );
}

/* --------------------------------------------------- sticky progress rail */

function ProgressRail() {
  return (
    <nav
      aria-label="Chapter progress"
      className="fixed right-4 top-1/2 z-40 hidden -translate-y-1/2 flex-col lg:flex"
    >
      {CHAPTERS.map((c) => (
        <a
          key={c.id}
          href={`#${c.id}`}
          aria-label={`Chapter ${c.n} — ${c.title}`}
          className="group flex h-11 items-center justify-end gap-2.5 px-2 font-mono text-[11px] text-muted transition-colors hover:text-cryo focus-visible:text-cryo"
        >
          <span>{c.n}</span>
          <span
            aria-hidden
            className="h-1.5 w-1.5 rounded-full bg-white/25 transition-colors group-hover:bg-cryo group-focus-visible:bg-cryo"
          />
        </a>
      ))}
    </nav>
  );
}

/* ---------------------------------------------------------------- footer */

function Footer() {
  return (
    <footer className="hairline">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 font-mono text-[12px] text-muted sm:flex-row sm:items-center sm:justify-between">
        <p>
          <ExtLink href={`${REPO}/blob/main/LICENSE`}>MIT</ExtLink> © 2026
          Advance Labs Inc. — a Canadian software studio.
        </p>
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <Link href="/" className="transition-colors hover:text-cryo">
            ← research home
          </Link>
          <ExtLink href={RESEARCH_DOC}>research doc 04</ExtLink>
          <ExtLink href={REPO}>github.com/Advance-Labs</ExtLink>
        </div>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ page */

export default function LearnPage() {
  return (
    <main className="flex-1">
      <TopBar />
      <Hero />
      <ProgressRail />
      <ChaptersIsland />
      <Footer />
    </main>
  );
}
