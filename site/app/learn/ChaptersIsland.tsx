"use client";

import dynamic from "next/dynamic";

/**
 * Client island for the chapter stack. `dynamic(..., { ssr: false })` is
 * only legal inside a client component in Next 16, so this thin wrapper is
 * what the server page imports; the heavy three.js graph (SharedCanvas +
 * five chapters) stays out of the server render entirely (research doc 04
 * §3; same pattern as the landing page's BlochHero → BlochScene).
 */
const Chapters = dynamic(() => import("./Chapters"), {
  ssr: false,
  loading: () => (
    <div className="hairline">
      <p className="mx-auto max-w-6xl px-6 py-24 font-mono text-[12px] tracking-[0.18em] text-muted">
        LOADING THE STATEVECTOR…
      </p>
    </div>
  ),
});

export default function ChaptersIsland() {
  return <Chapters />;
}
