import type { Metadata } from "next";
import Link from "next/link";
import { TopBar, Footer } from "@/components/site/SiteChrome";

const REPO = "https://github.com/Advance-Labs/quantum-hybrid-research";
const blob = (path: string) => `${REPO}/blob/main/${path}`;
const ADVANCE = "https://advancelabs.dev";

export const metadata: Metadata = {
  title: "The Quantum Road to Trillion-Parameter Models — Whitepaper",
  description:
    "A long-horizon, claim-tagged whitepaper on whether quantum computing can accelerate LLM training. The three walls, the quantum-inspired methods cutting model costs today, and a dated roadmap — grounded in our own 6-qubit benchmark.",
  alternates: { canonical: "https://quantum.advancelabs.dev/whitepaper" },
};

/* ----------------------------------------------------------------- shared */

function ClaimTag({ kind }: { kind: "Proven" | "Demonstrated" | "Theoretical" | "Speculative" }) {
  const map = {
    Proven: "text-proven border-proven/40",
    Demonstrated: "text-cryo border-cryo/40",
    Theoretical: "text-theory border-theory/40",
    Speculative: "text-spec border-spec/40",
  } as const;
  return (
    <span className={`mr-2 inline-block border ${map[kind]} px-1.5 py-0.5 align-middle font-mono text-[10px]`}>
      {kind}
    </span>
  );
}

function SectionHeading({ n, title }: { n: string; title: string }) {
  return (
    <div className="flex items-baseline gap-4">
      <span className="font-mono text-[13px] text-cryo">{n}</span>
      <h2 className="font-serif text-3xl text-paper sm:text-4xl">{title}</h2>
    </div>
  );
}

function Ext({ href, children }: { href: string; children: React.ReactNode }) {
  const external = href.startsWith("http");
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className="underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60"
    >
      {children}
    </a>
  );
}

/* ------------------------------------------------------------------- data */

const WALLS = [
  {
    n: "01",
    term: "The clock-speed deficit",
    kind: "Theoretical" as const,
    body: "Per operation, a quantum computer runs roughly 8–10 orders of magnitude slower than a classical FLOP. Stack error-correction overhead and the parallelism-per-dollar of a GPU cluster on top and the external survey literature estimates an aggregate handicap on the order of 10¹³. A polynomial — even quadratic — speedup cannot claw back a 13-zero head start at any problem size that fits a real training run.",
  },
  {
    n: "02",
    term: "Loading the data (QRAM)",
    kind: "Theoretical" as const,
    body: "LLMs train on trillions of tokens of classical text. Getting that data into a quantum state needs QRAM, which the literature judges may be an engineering challenge on par with building a fault-tolerant quantum computer — or infeasible. The on-ramp, not the engine, is the bottleneck.",
  },
  {
    n: "03",
    term: "Dequantization",
    kind: "Demonstrated" as const,
    body: "A class of supervised quantum models — quantum neural networks and quantum kernels for regression and classification — can be approximated classically via random Fourier features. Where it applies, the quantum model was doing nothing a clever classical method couldn't replicate. The first question a reviewer asks: did you rule out the classical shortcut?",
  },
];

const ROADMAP = [
  ["Dec 2024", "Google Willow", "Demonstrated", "“Below threshold” error correction — a logical qubit whose error rate falls as the code grows."],
  ["2026", "IBM Kookaburra", "Speculative", "First fault-tolerant module — logic and memory integrated. (Vendor roadmap.)"],
  ["2028–29", "IBM Starling", "Speculative", "~200 logical qubits running 100M+ operations. (Vendor roadmap.)"],
  ["2033+", "IBM Blue Jay", "Speculative", "2,000+ logical qubits at billion-gate scale. (Vendor roadmap.)"],
] as const;

/* ------------------------------------------------------------------- page */

export default function WhitepaperPage() {
  return (
    <main className="flex-1">
      <TopBar active="whitepaper" />

      {/* Header */}
      <section className="mx-auto max-w-3xl px-6 pb-16 pt-16 sm:pt-24">
        <p className="font-mono text-[12px] tracking-[0.18em] text-muted">
          WHITEPAPER · COMPANION TO{" "}
          <Ext href={blob("docs/research/01-qml-accelerator.md")}>STUDY 01 — QML-ACCELERATOR</Ext>
        </p>
        <h1 className="mt-6 font-serif text-5xl leading-[1.05] text-paper sm:text-6xl">
          The quantum road to trillion-parameter models
        </h1>
        <p className="mt-4 font-serif text-2xl italic text-cryo">A milestone map, not a miracle.</p>
        <p className="mt-6 text-[15px] leading-relaxed text-muted">
          Can quantum computing accelerate LLM training? We spent a month on the physics — then
          ran the experiment ourselves. This is the long-horizon read; the data, code, and
          per-claim epistemic tags live in the{" "}
          <Ext href={REPO}>research repository</Ext>. Built by{" "}
          <Ext href={ADVANCE}>Advance Labs</Ext>, the studio behind this initiative.
        </p>

        {/* Claim-tag legend */}
        <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 border-t border-white/8 pt-6">
          {(["Proven", "Demonstrated", "Theoretical", "Speculative"] as const).map((k) => (
            <span key={k} className="font-mono text-[11px] text-muted">
              <ClaimTag kind={k} />
              {k === "Proven" && "mathematically certain"}
              {k === "Demonstrated" && "shown on real hardware / verified"}
              {k === "Theoretical" && "rigorous, unproven"}
              {k === "Speculative" && "vendor roadmap / extrapolation"}
            </span>
          ))}
        </div>
      </section>

      {/* Exec summary */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="00" title="The honest answer" />
          <div className="mt-8 border-l-2 border-spec/50 pl-6">
            <p className="font-serif text-2xl leading-snug text-paper">
              Quantum computing cannot accelerate large-scale LLM training today, and the most
              rigorous analyses put meaningful impact <em className="text-cryo">a decade or two</em>{" "}
              out — into the 2040s on the pessimistic end, with the core matrix workloads past 2050.
            </p>
          </div>
          <p className="mt-6 text-[15px] leading-relaxed text-paper/80">
            That is the defensible version of an ambitious claim. It concedes what the skeptics get
            right and still leaves a real road to map. And we did not take it on faith — our own
            Study 01 built a 6-qubit hybrid adapter and measured it against a parameter-matched
            classical control.
          </p>
          <div className="mt-8 grid gap-px bg-white/8 sm:grid-cols-2">
            <div className="bg-ink p-6">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">THE HYBRID RAN</p>
              <p className="mt-2 font-serif text-3xl text-paper">6.45 → 6.04</p>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">
                training loss over 15 steps — the quantum adapter does learn.
              </p>
            </div>
            <div className="bg-ink p-6">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">THE CLASSICAL CONTROL WON</p>
              <p className="mt-2 font-serif text-3xl text-cryo">6.36 → 5.93</p>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">
                better loss, zero quantum circuits — at parameter parity.
              </p>
            </div>
          </div>
          <p className="mt-6 border-l-2 border-white/15 pl-4 font-mono text-[12px] leading-relaxed text-muted">
            <ClaimTag kind="Demonstrated" />
            71,040 circuit executions to lose to one classical forward/backward pass. Readiness:{" "}
            <span className="text-spec">2/10</span>. Full logs:{" "}
            <Ext href={blob("qml-accelerator/benchmarks/hybrid_run_log.json")}>hybrid_run_log.json</Ext>.
          </p>
        </div>
      </section>

      {/* Section 1 — intuition */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="01" title="Why the dream is seductive" />
          <p className="mt-8 text-[15px] leading-relaxed text-paper/80">
            The intuition is clean: a qubit superposes 0 and 1, <em>n</em> qubits represent 2ⁿ
            states at once, training is a search over an astronomically large parameter space —
            so a quantum computer should search it exponentially faster. It is also wrong in a
            specific, instructive way. Superposition does not hand you 2ⁿ answers you can read
            out; measurement collapses the state to one result, and extracting anything useful
            needs interference engineered to amplify right answers and cancel wrong ones. Only a
            handful of problems are known to admit that structure. &ldquo;Train a transformer on
            ten trillion tokens&rdquo; is not yet one of them.
          </p>
        </div>
      </section>

      {/* Section 2 — three walls */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="02" title="The three walls" />
          <p className="mt-6 text-[15px] leading-relaxed text-muted">
            None of them is qubit count. Each carries its evidence tag.
          </p>
          <div className="mt-10 space-y-px bg-white/8">
            {WALLS.map((w) => (
              <div key={w.n} className="bg-ink p-7">
                <div className="flex items-baseline gap-4">
                  <span className="font-mono text-[12px] text-muted">{w.n}</span>
                  <h3 className="font-serif text-2xl text-paper">{w.term}</h3>
                </div>
                <p className="mt-4 text-[14px] leading-relaxed text-paper/80">
                  <ClaimTag kind={w.kind} />
                  {w.body}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-8 text-[14px] leading-relaxed text-muted">
            The verdict of the careful: meaningful quantum impact on deep learning is{" "}
            <span className="text-paper">a decade or two</span> away. We take that as the
            foundation, not the ceiling, of the vision that follows. Full derivation in{" "}
            <Ext href={blob("docs/research/01-qml-accelerator.md")}>01-qml-accelerator.md</Ext>.
          </p>
        </div>
      </section>

      {/* Section 3 — what's already real */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="03" title="The part that is already real" />
          <p className="mt-8 text-[15px] leading-relaxed text-paper/80">
            You do not need a quantum <span className="text-paper">computer</span> to use quantum{" "}
            <span className="text-paper">math</span>. Tensor networks — born from entanglement
            physics — describe systems with astronomically many states using only the correlations
            that matter, and that turns out to describe the redundancy inside a neural network too.
          </p>
          <div className="mt-8 border border-white/8 p-6">
            <p className="text-[14px] leading-relaxed text-paper/80">
              <ClaimTag kind="Demonstrated" />
              CompactifAI (peer-reviewed, ESANN 2025) decomposes attention and feed-forward weight
              matrices into Matrix Product Operators. On LLaMA-2 7B: ~70% fewer parameters, ~93%
              smaller memory (paired with quantization), ~25% faster inference, 2–3% accuracy drop.
            </p>
            <p className="mt-4 text-[13px] leading-relaxed text-muted">
              The honest caveat, because this is where it is usually oversold: these methods compress
              a <em>finished</em> model — they do not make the expensive pretraining cheaper. The
              ~50% speedup is on the brief post-compression &ldquo;healing&rdquo; retrain, not on
              training from scratch. Still real, still useful, still running on classical GPUs today.
            </p>
          </div>
          <p className="mt-6 text-[15px] leading-relaxed text-muted">
            The quantum future is decades out. The quantum-<em>inspired</em> present is shipping.
          </p>
        </div>
      </section>

      {/* Section 4 — milestone map */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="04" title="The milestone map" />
          <p className="mt-6 text-[15px] leading-relaxed text-muted">
            A vision is only credible if it is dated. Read each milestone in two columns — what
            quantum could unlock, versus what a GPU cluster will be doing by the same year. Through
            the 2020s, classical wins decisively. The honest gap is the roadmap.
          </p>
          <div className="mt-10 space-y-px bg-white/8">
            {ROADMAP.map(([year, name, kind, body]) => (
              <div key={name} className="flex items-start gap-5 bg-ink p-6">
                <span className="w-20 shrink-0 font-mono text-[12px] font-medium tracking-wide text-cryo">
                  {year}
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="font-serif text-xl text-paper">{name}</h3>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-paper/75">
                    <ClaimTag kind={kind as "Demonstrated" | "Speculative"} />
                    {body}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Section 5 — where it lands first */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="05" title="Where the narrow speedups land first" />
          <p className="mt-8 text-[15px] leading-relaxed text-paper/80">
            When quantum does contribute to ML, it arrives as a targeted subroutine in an otherwise
            classical pipeline — never as &ldquo;quantum trains your model.&rdquo; Ranked by real
            plausibility:
          </p>
          <ol className="mt-6 space-y-4">
            {[
              ["Quantum-native data", "Chemistry, materials, sensing — data born quantum that never has to be loaded in. Sidesteps the data wall entirely. Best near-term bet."],
              ["Linear algebra with small outputs", "Pull a tiny answer from a huge computation, where measurement cost doesn't dominate."],
              ["Combinatorial optimization", "The one everyone hypes, and the weakest — Grover-style speedups need implausibly large instances and degrade under noisy objectives."],
            ].map(([t, b], i) => (
              <li key={t} className="flex gap-4">
                <span className="font-mono text-[12px] text-muted">{String(i + 1).padStart(2, "0")}</span>
                <span className="text-[14px] leading-relaxed text-paper/80">
                  <span className="text-paper">{t}.</span> {b}
                </span>
              </li>
            ))}
          </ol>
          <p className="mt-6 text-[14px] leading-relaxed text-muted">
            Notice what is not on the list: training a transformer. Build for insertion, not
            replacement.
          </p>
        </div>
      </section>

      {/* Section 6 — position + CTA with backlinks */}
      <section className="hairline">
        <div className="mx-auto max-w-3xl px-6 py-16">
          <SectionHeading n="06" title="The position" />
          <p className="mt-8 text-[15px] leading-relaxed text-paper/80">
            The winning posture is optionality — refuse both the hype and the dismissal. Harvest the
            quantum-inspired wins now, architect classical pipelines so quantum subroutines can slot
            in later, and track logical-qubit counts instead of press releases. That discernment —
            telling a real frontier from a marketed one — is what{" "}
            <Ext href={ADVANCE}>Advance Labs</Ext> builds for.
          </p>

          <div className="mt-10 grid gap-px bg-white/8 sm:grid-cols-2">
            <a
              href={ADVANCE}
              target="_blank"
              rel="noopener noreferrer"
              className="group bg-ink p-7 transition-colors hover:bg-white/[0.03]"
            >
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">THE STUDIO</p>
              <p className="mt-3 font-serif text-2xl text-paper group-hover:text-cryo">
                advancelabs.dev ↗
              </p>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
                We build AI systems — and the judgment to know which frontiers are real. Work with us.
              </p>
            </a>
            <a
              href={`${ADVANCE}/quantum`}
              target="_blank"
              rel="noopener noreferrer"
              className="group bg-ink p-7 transition-colors hover:bg-white/[0.03]"
            >
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">THE PDF</p>
              <p className="mt-3 font-serif text-2xl text-paper group-hover:text-cryo">
                Get the whitepaper ↗
              </p>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
                Prefer it as a designed PDF, or want the next one? Grab it on advancelabs.dev — email only.
              </p>
            </a>
          </div>

          <p className="mt-10 font-mono text-[12px] text-muted">
            Read deeper:{" "}
            <Ext href={blob("docs/research/01-qml-accelerator.md")}>the full Study 01 research doc</Ext>{" "}
            · <Link href="/whitepaper/summary" className="underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60">the one-screen summary</Link>{" "}
            · <Link href="/" className="underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60">all three studies</Link>
          </p>
        </div>
      </section>

      <Footer />
    </main>
  );
}
