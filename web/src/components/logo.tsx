import { cn } from "@/lib/utils";

/** The mark: a pulse line on a rounded square. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("shrink-0", className)}>
      <defs>
        <linearGradient id="tri-al-logo" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3b8ae6" />
          <stop offset="1" stopColor="#1c5cab" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#tri-al-logo)" />
      <path
        d="M8 20.5h3.2L14 11l3.6 10.5 2.4-5 1.4 4H24"
        fill="none"
        stroke="#fff"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
