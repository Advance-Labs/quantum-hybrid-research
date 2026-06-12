import Link from "next/link";
import BlochHero from "@/components/bloch/BlochHero";

const REPO = "https://github.com/Advance-Labs/quantum-hybrid-research";
const blob = (path: string) => `${REPO}/blob/main/${path}`;
const tree = (path: string) => `${REPO}/tree/main/${path}`;

/* ---------------------------------------------------------------- shared */

function SectionHeading({ n, title }: { n: string; title: string }) {
  return (
    <div className="flex items-baseline gap-4">
      <span className="font-mono text-[13px] text-cryo">{n}</span>
      <h2 className="font-serif text-3xl text-paper sm:text-4xl">{title}</h2>
    </div>
  );
}

function ExtLink({
  href,
  children,
  className = "",
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  const external = href.startsWith("http");
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className={`underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60 ${className}`}
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
        <p className="font-mono text-[12px] tracking-[0.18em] text-paper">
          QUANTUM-HYBRID RESEARCH
        </p>
        <nav className="flex items-center gap-6 font-mono text-[12px] text-muted">
          <Link href="/whitepaper" className="transition-colors hover:text-cryo">
            Whitepaper
          </Link>
          <Link href="/learn" className="transition-colors hover:text-cryo">
            Learn ↗
          </Link>
          <a
            href="https://advancelabs.dev"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-cryo"
          >
            Advance Labs ↗
          </a>
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

const TAGS = [
  { name: "Proven", color: "bg-proven", desc: "mathematically proven" },
  { name: "Demonstrated", color: "bg-cryo", desc: "shown on real hardware" },
  { name: "Theoretical", color: "bg-theory", desc: "rigorous, unproven" },
  { name: "Speculative", color: "bg-spec", desc: "extrapolation" },
];

function Hero() {
  return (
    <section className="mx-auto grid max-w-6xl grid-cols-1 gap-12 px-6 pb-20 pt-16 sm:pt-24 lg:grid-cols-2 lg:gap-16">
      <div className="flex flex-col justify-center">
        <p
          className="rise font-mono text-[12px] tracking-[0.18em] text-muted"
          style={{ animationDelay: "0ms" }}
        >
          AN ADVANCE LABS RESEARCH INITIATIVE
        </p>
        <h1
          className="rise mt-6 font-serif text-5xl leading-[1.05] text-paper sm:text-6xl"
          style={{ animationDelay: "90ms" }}
        >
          Where quantum meets classical,{" "}
          <em className="text-cryo">measured honestly</em>.
        </h1>
        <p
          className="rise mt-6 max-w-xl text-[15px] leading-relaxed text-muted"
          style={{ animationDelay: "180ms" }}
        >
          Three feasibility studies — quantum-accelerated LLM training, Linux
          as the control plane for quantum hardware, and a hybrid
          classical/quantum motherboard — plus QLOS&nbsp;v0.1, a user-space
          quantum OS runtime backed by a 228-test emulator and toolchain. The
          conclusions are sober; the code exists to measure, not to sell.
        </p>
        <div
          className="rise mt-8 flex flex-wrap gap-x-6 gap-y-2"
          style={{ animationDelay: "270ms" }}
        >
          {TAGS.map((t) => (
            <span
              key={t.name}
              className="flex items-center gap-2 font-mono text-[11px] text-muted"
            >
              <span className={`h-1.5 w-1.5 rounded-full ${t.color}`} />
              [{t.name}] {t.desc}
            </span>
          ))}
        </div>
        <div
          className="rise mt-10 flex flex-wrap gap-3"
          style={{ animationDelay: "360ms" }}
        >
          <Link
            href="/learn"
            className="border border-cryo/60 px-5 py-2.5 font-mono text-[12px] tracking-wider text-cryo transition-colors hover:bg-cryo/10"
          >
            LEARN HOW IT WORKS →
          </Link>
          <a
            href={REPO}
            target="_blank"
            rel="noopener noreferrer"
            className="border border-white/15 px-5 py-2.5 font-mono text-[12px] tracking-wider text-muted transition-colors hover:border-white/40 hover:text-paper"
          >
            READ THE RESEARCH ↗
          </a>
          <a
            href="#verdicts"
            className="border border-white/15 px-5 py-2.5 font-mono text-[12px] tracking-wider text-muted transition-colors hover:border-white/40 hover:text-paper"
          >
            THE VERDICTS ↓
          </a>
        </div>
      </div>
      <div className="rise" style={{ animationDelay: "200ms" }}>
        <BlochHero />
        <p className="mt-3 font-mono text-[11px] text-muted">
          Fig. 0 — a live single-qubit statevector on the Bloch sphere. H, X,
          Z, S are the real unitaries.
        </p>
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- verdicts */

interface Verdict {
  num: string;
  name: string;
  question: string;
  verdict: string;
  verdictTone: string;
  detail: string;
  datum: string;
  research: string;
  code: string;
  codeLabel: string;
}

const VERDICTS: Verdict[] = [
  {
    num: "I",
    name: "QML-Accelerator",
    question: "Can quantum subroutines accelerate LLM training?",
    verdict: "Not before the mid-2030s. Readiness 2/10.",
    verdictTone: "text-spec",
    detail:
      "The asymptotic speedups are real but narrow; I/O bottlenecks are severe and the quantum clock-speed deficit is ~8–10 orders of magnitude. The verdict is now empirical: a 6-qubit hybrid adapter trains (loss 6.45 → 6.04 over 15 steps) — but its parameter-matched classical control trains better (6.36 → 5.93) while executing zero quantum circuits.",
    datum: "71,040 circuit executions to lose to one forward/backward pass",
    research: blob("docs/research/01-qml-accelerator.md"),
    code: tree("qml-accelerator"),
    codeLabel: "qml-accelerator/",
  },
  {
    num: "II",
    name: "QuantumLinux",
    question: "Can the Linux kernel be ported to quantum hardware?",
    verdict: "Impossible in principle — and that's the finding.",
    verdictTone: "text-theory",
    detail:
      "A literal port is ruled out by the [Proven] no-cloning theorem and measurement postulate: fork(), copy-on-write, and preemption have no physical realization for quantum state. Linux as the classical control plane, via a narrow QALLOC/QEXEC/QMEASURE/QFREE syscall interface, is the only viable design — and QLOS v0.1 implements it in user space.",
    datum: "228/228 tests passing — emulator, runtime, toolchain, kernel-init",
    research: blob("docs/research/02-quantum-linux.md"),
    code: tree("quantum-linux"),
    codeLabel: "quantum-linux/",
  },
  {
    num: "III",
    name: "HybridBoard",
    question: "Can a QPU live on a motherboard next to a CPU and GPU?",
    verdict: "The binding constraint is latency, not bandwidth.",
    verdictTone: "text-cryo",
    detail:
      "The control loop must close well inside qubit coherence times. For superconducting QPUs a \"motherboard\" is a category error — the system is a rack-and-cryostat installation — and no consumer market exists today. The QCX bus spec, ACPI QDEV firmware model, and hybrid scheduler map exactly where the bottlenecks are.",
    datum: "≤2 µs control loop over the QCX bus, or the qubits decohere",
    research: blob("docs/research/03-hybrid-board.md"),
    code: tree("hybrid-board"),
    codeLabel: "hybrid-board/",
  },
];

function Verdicts() {
  return (
    <section id="verdicts" className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <SectionHeading n="01" title="Three questions, three honest answers" />
        <div className="mt-12 grid gap-px bg-white/8 md:grid-cols-3">
          {VERDICTS.map((v) => (
            <article key={v.num} className="flex flex-col bg-ink p-7">
              <p className="font-mono text-[12px] text-muted">{v.num}</p>
              <h3 className="mt-4 font-serif text-2xl text-paper">{v.name}</h3>
              <p className="mt-2 text-[14px] leading-relaxed text-muted">
                {v.question}
              </p>
              <p
                className={`mt-5 font-serif text-lg leading-snug ${v.verdictTone}`}
              >
                {v.verdict}
              </p>
              <p className="mt-4 flex-1 text-[13.5px] leading-relaxed text-paper/75">
                {v.detail}
              </p>
              <p className="mt-5 border-l-2 border-white/15 pl-3 font-mono text-[11.5px] leading-relaxed text-muted">
                {v.datum}
              </p>
              <div className="mt-6 flex flex-wrap gap-x-5 gap-y-2 font-mono text-[12px]">
                <ExtLink href={v.research}>research →</ExtLink>
                <ExtLink href={v.code}>{v.codeLabel}</ExtLink>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ QLOS panel */

const DEV_LOOP = [
  {
    step: "edit",
    cmd: "$EDITOR examples/bell.qs",
    note: "write QISA-K assembly",
  },
  {
    step: "cc",
    cmd: "python toolchain/qas.py examples/bell.qs -o /tmp/bell.qobj.json",
    note: "assemble → QOBJ v0.1, validated against the ISA spec",
  },
  {
    step: "exec",
    cmd: "python examples/qrun.py examples/bell.qs --shots 1024",
    note: "submit through qalloc / qexec / qmeasure / qfree",
  },
  {
    step: "gdb",
    cmd: "python examples/qrun.py examples/bell.qs --trace --seed 42",
    note: "single-step one shot, per-instruction amplitudes",
  },
  {
    step: "objdump",
    cmd: "python toolchain/qdis.py /tmp/bell.qobj.json",
    note: "disassemble back to canonical .qs — round-trip safe",
  },
];

const TEST_SPLIT = [
  { n: 72, label: "emulator" },
  { n: 55, label: "QLOS runtime + scheduler" },
  { n: 85, label: "toolchain" },
  { n: 16, label: "kernel-init" },
];

function QlosPanel() {
  return (
    <section className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <SectionHeading
          n="02"
          title="QLOS v0.1 — a normalized dev loop for quantum hardware"
        />
        <div className="mt-12 grid grid-cols-1 gap-12 lg:grid-cols-[5fr_7fr]">
          <div>
            <p className="text-[15px] leading-relaxed text-muted">
              No operating system can ever run <em>on</em> a QPU — a corollary
              of the no-cloning theorem, not an engineering gap. What can
              exist is the control plane. QLOS v0.1 realizes it in user space:
              a classical runtime that leases qubits, verifies and schedules
              circuits, and returns only classical measurement shadows through
              a four-call discipline.
            </p>
            <div className="mt-7 flex flex-wrap gap-2 font-mono text-[12px]">
              {["QALLOC", "QEXEC", "QMEASURE", "QFREE"].map((s) => (
                <span
                  key={s}
                  className="border border-cryo/40 px-3 py-1.5 text-cryo"
                >
                  {s}
                </span>
              ))}
            </div>
            <p className="mt-7 text-[14px] leading-relaxed text-muted">
              Because quantum state can never be inspected after the fact,
              assemble-time validation against{" "}
              <ExtLink href={blob("quantum-linux/isa-spec/QISA-v0.1.yaml")}>
                QISA-v0.1.yaml
              </ExtLink>{" "}
              plays the role the MMU plays classically: reject the program
              before any state exists. The binding contract is{" "}
              <ExtLink href={blob("quantum-linux/qos/QLOS-DESIGN-v0.1.md")}>
                QLOS-DESIGN-v0.1.md
              </ExtLink>
              .
            </p>
            <div className="mt-9 border border-white/8 p-5">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">
                TEST SUITE
              </p>
              <p className="mt-2 font-serif text-4xl text-paper">
                228<span className="text-muted">/228</span>
              </p>
              <div className="mt-4 space-y-1.5 font-mono text-[12px] text-muted">
                {TEST_SPLIT.map((t) => (
                  <p key={t.label} className="flex justify-between gap-4">
                    <span>{t.label}</span>
                    <span className="text-paper">{t.n}</span>
                  </p>
                ))}
              </div>
              <p className="mt-4 font-mono text-[11px] text-muted">
                Run on every push by{" "}
                <ExtLink href={blob(".github/workflows/ci.yml")}>
                  ci.yml
                </ExtLink>
              </p>
            </div>
          </div>
          <div className="border border-white/8 bg-white/[0.02]">
            <div className="flex items-center justify-between border-b border-white/8 px-5 py-3">
              <p className="font-mono text-[11px] tracking-[0.18em] text-muted">
                EDIT → CC → EXEC → GDB → OBJDUMP
              </p>
              <ExtLink
                href={blob("quantum-linux/examples/bell.qs")}
                className="font-mono text-[11px]"
              >
                bell.qs
              </ExtLink>
            </div>
            <div className="space-y-5 overflow-x-auto p-5">
              {DEV_LOOP.map((d) => (
                <div key={d.step}>
                  <p className="font-mono text-[11px] text-muted">
                    <span className="text-theory"># {d.step}</span> — {d.note}
                  </p>
                  <p className="mt-1 whitespace-nowrap font-mono text-[12.5px] text-paper">
                    <span className="text-cryo">$ </span>
                    {d.cmd}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* -------------------------------------------------------- research index */

interface IndexRow {
  num: string;
  title: string;
  readiness: string;
  tone: string;
  research: { href: string; label: string };
  workflow?: { href: string; label: string };
  code?: { href: string; label: string };
}

const INDEX: IndexRow[] = [
  {
    num: "01",
    title: "Quantum speedup analysis for LLM training",
    readiness: "2/10",
    tone: "text-spec",
    research: {
      href: blob("docs/research/01-qml-accelerator.md"),
      label: "01-qml-accelerator.md",
    },
    workflow: {
      href: blob("docs/workflows/01-qml-workflow.md"),
      label: "01-qml-workflow.md",
    },
    code: { href: tree("qml-accelerator"), label: "qml-accelerator/" },
  },
  {
    num: "02",
    title: "Linux-on-quantum feasibility, QISA-K, emulator, QLOS",
    readiness: "control plane only",
    tone: "text-theory",
    research: {
      href: blob("docs/research/02-quantum-linux.md"),
      label: "02-quantum-linux.md",
    },
    workflow: {
      href: blob("docs/workflows/02-linux-workflow.md"),
      label: "02-linux-workflow.md",
    },
    code: { href: tree("quantum-linux"), label: "quantum-linux/" },
  },
  {
    num: "03",
    title: "Classical/quantum motherboard architecture",
    readiness: "latency-bound",
    tone: "text-cryo",
    research: {
      href: blob("docs/research/03-hybrid-board.md"),
      label: "03-hybrid-board.md",
    },
    workflow: {
      href: blob("docs/workflows/03-hybridboard-workflow.md"),
      label: "03-hybridboard-workflow.md",
    },
    code: { href: tree("hybrid-board"), label: "hybrid-board/" },
  },
  {
    num: "04",
    title: "Web-based 3D quantum visualization for education",
    readiness: "8/10",
    tone: "text-proven",
    research: {
      href: blob("docs/research/04-quantum-viz-education.md"),
      label: "04-quantum-viz-education.md",
    },
    code: { href: tree("site"), label: "site/ — this page" },
  },
  {
    num: "05",
    title: "Interactive explainer — learn quantum computing in the browser",
    readiness: "live",
    tone: "text-proven",
    research: {
      href: blob("docs/research/04-quantum-viz-education.md"),
      label: "04-quantum-viz-education.md",
    },
    code: { href: "/learn", label: "/learn — try it" },
  },
];

function ResearchIndex() {
  return (
    <section className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <SectionHeading n="03" title="Research index" />
        <p className="mt-5 max-w-2xl text-[14px] leading-relaxed text-muted">
          Recommended reading order per project: research document → workflow
          → code. Every document carries per-claim epistemic tags.
        </p>
        <div className="mt-10 overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left">
            <thead>
              <tr className="border-b border-white/15 font-mono text-[11px] tracking-[0.15em] text-muted">
                <th className="py-3 pr-4 font-medium">№</th>
                <th className="py-3 pr-4 font-medium">STUDY</th>
                <th className="py-3 pr-4 font-medium">RESEARCH</th>
                <th className="py-3 pr-4 font-medium">WORKFLOW</th>
                <th className="py-3 pr-4 font-medium">CODE</th>
                <th className="py-3 font-medium">VERDICT</th>
              </tr>
            </thead>
            <tbody className="text-[13.5px]">
              {INDEX.map((r) => (
                <tr key={r.num} className="border-b border-white/8 align-top">
                  <td className="py-4 pr-4 font-mono text-[12px] text-muted">
                    {r.num}
                  </td>
                  <td className="max-w-[260px] py-4 pr-4 leading-snug text-paper">
                    {r.title}
                  </td>
                  <td className="py-4 pr-4 font-mono text-[12px]">
                    <ExtLink href={r.research.href}>{r.research.label}</ExtLink>
                  </td>
                  <td className="py-4 pr-4 font-mono text-[12px]">
                    {r.workflow ? (
                      <ExtLink href={r.workflow.href}>
                        {r.workflow.label}
                      </ExtLink>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="py-4 pr-4 font-mono text-[12px]">
                    {r.code ? (
                      <ExtLink href={r.code.href}>{r.code.label}</ExtLink>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className={`py-4 font-mono text-[12px] ${r.tone}`}>
                    {r.readiness}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-6 font-mono text-[11.5px] text-muted">
          Committed reference artifacts:{" "}
          <ExtLink
            href={blob("qml-accelerator/benchmarks/classical_baseline.json")}
          >
            classical_baseline.json
          </ExtLink>{" "}
          ·{" "}
          <ExtLink
            href={blob("qml-accelerator/benchmarks/hybrid_run_log.json")}
          >
            hybrid_run_log.json
          </ExtLink>{" "}
          ·{" "}
          <ExtLink
            href={blob("quantum-linux/emulator/results/init-report.json")}
          >
            init-report.json
          </ExtLink>
        </p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ methodology */

const TAG_DEFS = [
  {
    tag: "[Proven]",
    color: "text-proven",
    border: "border-proven/40",
    desc: "Mathematically proven. The no-cloning theorem is why no OS will ever run on a QPU — no roadmap changes this.",
  },
  {
    tag: "[Demonstrated]",
    color: "text-cryo",
    border: "border-cryo/40",
    desc: "Experimentally shown on real hardware, or verified live against primary sources at the time of writing.",
  },
  {
    tag: "[Theoretical]",
    color: "text-theory",
    border: "border-theory/40",
    desc: "Rigorous but unproven in practice. Asymptotic speedups live here — real on paper, unrealized in any machine.",
  },
  {
    tag: "[Speculative]",
    color: "text-spec",
    border: "border-spec/40",
    desc: "Extrapolation or conjecture. In code, it becomes a labeled assumption with a tunable constant — never treated as free.",
  },
];

const CI_GATES = [
  "py_compile sweep over every Python file",
  "the 228-test quantum-linux pytest suite",
  "strict -Wall -Wextra -Werror C11 build of the scheduler demo",
  "YAML parse of the QISA-K instruction-set spec",
];

function Methodology() {
  return (
    <section className="hairline">
      <div className="mx-auto max-w-6xl px-6 py-20">
        <SectionHeading n="04" title="Every claim carries its evidence" />
        <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-muted">
          Untagged sentences are context, not claims. Tags are never silently
          promoted when material moves between documents, and citations were
          web-verified against the June 2026 state of the field.
        </p>
        <div className="mt-12 grid gap-px bg-white/8 sm:grid-cols-2 lg:grid-cols-4">
          {TAG_DEFS.map((t) => (
            <div key={t.tag} className="bg-ink p-6">
              <p
                className={`inline-block border ${t.border} px-2.5 py-1 font-mono text-[12px] ${t.color}`}
              >
                {t.tag}
              </p>
              <p className="mt-4 text-[13.5px] leading-relaxed text-paper/75">
                {t.desc}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-12 grid grid-cols-1 gap-10 lg:grid-cols-2">
          <div>
            <p className="font-mono text-[11px] tracking-[0.18em] text-muted">
              ENFORCED MECHANICALLY —{" "}
              <ExtLink href={blob(".github/workflows/ci.yml")}>
                .github/workflows/ci.yml
              </ExtLink>
            </p>
            <ul className="mt-4 space-y-2.5">
              {CI_GATES.map((g) => (
                <li
                  key={g}
                  className="flex gap-3 font-mono text-[12.5px] text-paper/80"
                >
                  <span className="text-proven">✓</span>
                  {g}
                </li>
              ))}
            </ul>
          </div>
          <p className="border-l-2 border-white/15 pl-5 font-serif text-xl leading-relaxed text-paper/85">
            Why explore it anyway? The hybrid classical/quantum split is the
            asymptotically correct division of labor, not a temporary
            compromise. Working out the map <em>now</em> — with every claim
            tagged — is cheap, and shows exactly where the bottlenecks are.
          </p>
        </div>
      </div>
    </section>
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
        <div className="flex gap-6">
          <a
            href="https://advancelabs.dev"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-cryo"
          >
            advancelabs.dev
          </a>
          <a
            href="https://github.com/Advance-Labs"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-cryo"
          >
            github.com/Advance-Labs
          </a>
        </div>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ page */

export default function Home() {
  return (
    <main className="flex-1">
      <TopBar />
      <Hero />
      <Verdicts />
      <QlosPanel />
      <ResearchIndex />
      <Methodology />
      <Footer />
    </main>
  );
}
