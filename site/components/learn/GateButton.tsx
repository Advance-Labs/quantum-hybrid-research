"use client";

/**
 * Square mono gate button — the hero's gate-button vocabulary at a
 * touch-first 44×44 px hit target (a11y contract §9). Hairline border;
 * hover and `active` (e.g. a selected palette gate awaiting wire placement)
 * go cryo-cyan. `aria-pressed` is exposed only when `active` is set so plain
 * apply-immediately buttons keep plain button semantics.
 */
export function GateButton({
  gate,
  onClick,
  ariaLabel,
  active = false,
  disabled = false,
}: {
  gate: string;
  onClick: () => void;
  ariaLabel: string;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-pressed={active || undefined}
      disabled={disabled}
      onClick={onClick}
      className={`flex h-11 w-11 shrink-0 items-center justify-center border font-mono text-[14px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "border-cryo text-cryo"
          : "border-white/15 text-paper enabled:hover:border-cryo enabled:hover:text-cryo"
      }`}
    >
      {gate}
    </button>
  );
}
