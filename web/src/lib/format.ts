/** Numbers, dates and codes as people read them. */

const integer = new Intl.NumberFormat("en-US");
const compactNumber = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const longDate = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});
const shortDate = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const dateTime = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const relative = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : integer.format(value);
}

const percent = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });
const smallPercent = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumSignificantDigits: 2,
});

/** A fraction as a percentage: 0.124 is "12.4%", and below 1% two digits show, so 0.00016
 * is "0.016%" rather than "0%". */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value > 0 && value < 0.01 ? smallPercent.format(value) : percent.format(value);
}

/** How a chart's numbers read (a chart spec's `format`). */
export type NumberFormat = "number" | "percent";

export function formatValue(value: number | null | undefined, format?: NumberFormat | null) {
  return format === "percent" ? formatPercent(value) : formatNumber(value);
}

export function formatCompact(value: number): string {
  return value < 10_000 ? integer.format(value) : compactNumber.format(value);
}

/** A `YYYY-MM-DD` date (stored without a time zone) as "Oct 16, 2026". */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : longDate.format(date);
}

export function formatShortDate(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : shortDate.format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateTime.format(date);
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** "3 minutes ago", "yesterday"; "just now" under a minute. */
export function formatRelative(value: string | number | Date, now = Date.now()): string {
  const time = value instanceof Date ? value.getTime() : new Date(value).getTime();
  if (Number.isNaN(time)) return "";
  const seconds = (time - now) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

/** Seconds as "1m 05s" or "4.2s". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** An age in days (a year is 365.25 days, as the API stores it) as "60 years" or "6 months". */
export function formatAge(days: number | null | undefined): string | null {
  if (days === null || days === undefined) return null;
  const years = days / 365.25;
  if (years >= 2) return `${Math.floor(years + 1e-9)} years`;
  const months = Math.floor(days / (365.25 / 12) + 1e-9);
  if (months >= 1) return `${months} month${months === 1 ? "" : "s"}`;
  const weeks = Math.floor(days / 7);
  if (weeks >= 1) return `${weeks} week${weeks === 1 ? "" : "s"}`;
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** `ACTIVE_NOT_RECRUITING` as "Active not recruiting", for codes without a label. */
export function humanize(code: string): string {
  const words = code.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const regions =
  typeof Intl.DisplayNames === "function"
    ? new Intl.DisplayNames(["en"], { type: "region", fallback: "code" })
    : null;

const OLD_REGIONS: Record<string, string> = {
  CS: "Serbia and Montenegro",
  YU: "Yugoslavia",
  AN: "Netherlands Antilles",
  XK: "Kosovo",
};

/** An ISO 3166-1 alpha-2 code's English name (the browser knows them all). */
export function countryName(code: string | null | undefined): string {
  if (!code) return "—";
  const upper = code.toUpperCase();
  if (OLD_REGIONS[upper]) return OLD_REGIONS[upper];
  try {
    return regions?.of(upper) ?? upper;
  } catch {
    return upper;
  }
}

/** The flag emoji for an alpha-2 code (regional indicator letters). */
export function flag(code: string | null | undefined): string {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return "";
  const base = 0x1f1e6 - 65;
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => base + c.charCodeAt(0)));
}
