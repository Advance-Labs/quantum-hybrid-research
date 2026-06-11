/**
 * Left-rule callout box. Three kinds, colored by the epistemic palette:
 *   misconception — spec-red rule + mono tag MISCONCEPTION (the Hu/Li/Singh
 *                   2024 counters, research doc 04 §5.3)
 *   note          — cryo-cyan rule + NOTE
 *   try           — proven-green rule + TRY IT
 * Server-safe (no hooks, no 'use client').
 */
export function Callout({
  kind,
  title,
  children,
}: {
  kind: "misconception" | "note" | "try";
  title: string;
  children: React.ReactNode;
}) {
  const k = {
    misconception: { tag: "MISCONCEPTION", rule: "border-spec", text: "text-spec" },
    note: { tag: "NOTE", rule: "border-cryo", text: "text-cryo" },
    try: { tag: "TRY IT", rule: "border-proven", text: "text-proven" },
  }[kind];

  return (
    <aside className={`border-l-2 ${k.rule} bg-white/[0.02] py-4 pl-5 pr-5`}>
      <p className={`font-mono text-[11px] tracking-[0.18em] ${k.text}`}>
        {k.tag}
      </p>
      <p className="mt-2 font-serif text-[19px] leading-snug text-paper">
        {title}
      </p>
      <div className="mt-2 max-w-prose text-[14px] leading-relaxed text-paper/75">
        {children}
      </div>
    </aside>
  );
}
