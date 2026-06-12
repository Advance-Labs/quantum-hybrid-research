import type { Metadata } from "next";
import Link from "next/link";
import { TopBar, Footer } from "@/components/site/SiteChrome";

const REPO = "https://github.com/Advance-Labs/quantum-hybrid-research";
const ADVANCE = "https://advancelabs.dev";

export const metadata: Metadata = {
  title: "Can Quantum Computing Accelerate LLM Training? — One-Screen Summary",
  description:
    "The ungated executive summary: the honest answer, the three walls, what already works on classical hardware, and a dated hardware roadmap. Grounded in our own 6-qubit benchmark.",
  alternates: { canonical: "https://quantum.advancelabs.dev/whitepaper/summary" },
};

function Ext({ href, children }: { href: string; children: React.ReactNode }) {
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

const TAKEAWAYS: [string, string][] = [
  ["The hype is wrong about timing.", "An estimated ~10¹³ aggregate hardware handicap, the unsolved data-loading problem, and dequantization push practical quantum LLM training well past the 2030s. Our own 6-qubit hybrid lost to its parameter-matched classical control."],
  ["But quantum-inspired methods already pay off — on classical hardware.", "Tensor-network compression (with quantization) shrank a 7B model's memory ~93% and halved its post-compression recovery-retrain. No quantum computer involved."],
  ["The roadmap is concrete, not hand-wavy.", "Fault-tolerant milestones now carry named processors and dates through 2033+ — enough to reason about when narrow quantum speedups could enter the pipeline."],
  ["The winning posture is optionality.", "Don't wait for fault-tolerance, don't dismiss it. Harvest what works now; architect so the hardware can slot in later."],
];

const ROADMAP: [string, string, string][] = [
  ["Dec 2024", "Google Willow", "“Below threshold” error correction — error rate falls as the code grows."],
  ["2026", "IBM Kookaburra", "First fault-tolerant module (vendor roadmap)."],
  ["2028–29", "IBM Starling", "~200 logical qubits, 100M+ operations (vendor roadmap)."],
  ["2033+", "IBM Blue Jay", "2,000+ logical qubits, billion-gate scale (vendor roadmap)."],
];

export default function SummaryPage() {
  return (
    <main className="flex-1">
      <TopBar active="whitepaper" />

      <section className="mx-auto max-w-3xl px-6 pb-12 pt-16 sm:pt-24">
        <p className="font-mono text-[12px] tracking-[0.18em] text-muted">
          EXECUTIVE SUMMARY · UNGATED
        </p>
        <h1 className="mt-6 font-serif text-4xl leading-[1.08] text-paper sm:text-5xl">
          Can quantum computing accelerate LLM training?
        </h1>
        <p className="mt-6 text-[15px] leading-relaxed text-muted">
          Every few months a headline says quantum computers are about to make AI training cheap.
          This is a reality check, then a map — grounded in our own experiment, not vibes. The full
          read is the <Link href="/whitepaper" className="underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60">whitepaper</Link>;
          the data lives in the <Ext href={REPO}>repository</Ext>; the studio is{" "}
          <Ext href={ADVANCE}>Advance Labs</Ext>.
        </p>
      </section>

      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-14">
          <div className="border-l-2 border-spec/50 pl-6">
            <p className="font-serif text-2xl leading-snug text-paper">
              Quantum computing cannot accelerate large-scale LLM training today. The most rigorous
              analyses put meaningful impact <em className="text-cryo">a decade or two</em> away —
              into the 2040s on the pessimistic end. Three walls stand in the way. But a real, dated
              road exists, and quantum-<em>inspired</em> math already pays off on ordinary GPUs.
            </p>
          </div>
        </div>
      </section>

      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-14">
          <h2 className="font-serif text-2xl text-paper">Four takeaways</h2>
          <div className="mt-8 space-y-px bg-white/8">
            {TAKEAWAYS.map(([t, b], i) => (
              <div key={t} className="flex gap-5 bg-ink p-6">
                <span className="font-mono text-[12px] text-cryo">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <p className="font-serif text-lg text-paper">{t}</p>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-muted">{b}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-14">
          <h2 className="font-serif text-2xl text-paper">The milestone map</h2>
          <div className="mt-8 space-y-px bg-white/8">
            {ROADMAP.map(([year, name, body]) => (
              <div key={name} className="flex items-start gap-5 bg-ink p-5">
                <span className="w-20 shrink-0 font-mono text-[12px] font-medium tracking-wide text-cryo">
                  {year}
                </span>
                <div>
                  <h3 className="font-serif text-lg text-paper">{name}</h3>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-14">
          <div className="grid gap-px bg-white/8 sm:grid-cols-2">
            <Link href="/whitepaper" className="group bg-ink p-7 transition-colors hover:bg-white/[0.03]">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">KEEP READING</p>
              <p className="mt-3 font-serif text-2xl text-paper group-hover:text-cryo">The full whitepaper →</p>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
                The three walls in detail, the empirical 6-qubit result, and where speedups land first.
              </p>
            </Link>
            <a href={`${ADVANCE}/quantum`} target="_blank" rel="noopener noreferrer" className="group bg-ink p-7 transition-colors hover:bg-white/[0.03]">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">THE STUDIO</p>
              <p className="mt-3 font-serif text-2xl text-paper group-hover:text-cryo">advancelabs.dev ↗</p>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
                Get the designed PDF and work with the team behind this research.
              </p>
            </a>
          </div>
        </div>
      </section>

      <Footer />
    </main>
  );
}
