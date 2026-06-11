"use client";

/**
 * Measurement-outcome histogram: horizontal mono bars inside a hairline
 * frame. Bar widths tween via CSS (`transition-[width]`, snapped under
 * prefers-reduced-motion with `motion-reduce:`). The count + percentage
 * text per row IS the accessibility fallback — the bars themselves are
 * aria-hidden and never the only carrier of the data.
 */
export function Histogram({
  counts,
  total,
  labels,
}: {
  counts: Record<string, number>;
  total: number;
  labels: string[];
}) {
  return (
    <div className="border border-white/8 bg-white/[0.02] p-4">
      <dl className="flex flex-col gap-2">
        {labels.map((label) => {
          const count = counts[label] ?? 0;
          const frac = total > 0 ? count / total : 0;
          const pct = (frac * 100).toFixed(1);
          return (
            <div key={label} className="flex items-center gap-3">
              <dt className="w-8 shrink-0 font-mono text-[12px] text-muted">
                {label}
              </dt>
              <dd className="flex min-w-0 flex-1 items-center gap-3">
                <span
                  className="relative h-2.5 min-w-0 flex-1 overflow-hidden border border-white/8"
                  aria-hidden
                >
                  <span
                    className="absolute inset-y-0 left-0 bg-cryo/50 transition-[width] duration-300 ease-out motion-reduce:transition-none"
                    style={{ width: `${frac * 100}%` }}
                  />
                </span>
                <span className="w-25 shrink-0 text-right font-mono text-[12px] tabular-nums text-paper/85">
                  {count} · {pct}%
                </span>
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="mt-3 font-mono text-[11px] text-muted">
        total shots: {total}
      </p>
    </div>
  );
}
