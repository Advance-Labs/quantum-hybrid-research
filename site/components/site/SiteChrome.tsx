import Link from "next/link";

const REPO = "https://github.com/Advance-Labs/quantum-hybrid-research";

/**
 * Shared top bar + footer, extracted so the whitepaper pages match the
 * homepage chrome exactly. The homepage keeps its own inline copies; this is
 * the canonical version for secondary routes.
 */

export function TopBar({ active }: { active?: "whitepaper" | "learn" }) {
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
          <Link
            href="/whitepaper"
            className={`transition-colors hover:text-cryo ${
              active === "whitepaper" ? "text-cryo" : ""
            }`}
          >
            Whitepaper
          </Link>
          <Link
            href="/learn"
            className={`transition-colors hover:text-cryo ${
              active === "learn" ? "text-cryo" : ""
            }`}
          >
            Learn ↗
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

export function Footer() {
  return (
    <footer className="hairline">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 font-mono text-[12px] text-muted sm:flex-row sm:items-center sm:justify-between">
        <p>
          <a
            href={`${REPO}/blob/main/LICENSE`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-white/25 underline-offset-4 transition-colors hover:text-cryo hover:decoration-cryo/60"
          >
            MIT
          </a>{" "}
          © 2026 Advance Labs Inc. — a Canadian software studio.
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
