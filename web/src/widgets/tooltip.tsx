import type { TooltipContentProps } from "recharts";
import { formatNumber } from "@/lib/format";

type Props = Partial<TooltipContentProps<number, string>> & {
  formatLabel?: (label: string) => string;
  /** A value as its series reads it (by the series' data key); plain numbers otherwise. */
  formatValue?: (value: number, dataKey: string) => string;
};

/** One series' tooltip: the value first and strong, then what it's for. */
export function SingleTooltip({ active, payload, label, formatLabel, formatValue }: Props) {
  const item = payload?.[0];
  if (!active || !item) return null;
  const name = String(label ?? item.payload?.label ?? "");
  return (
    <div className="grid min-w-28 gap-0.5 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <div className="flex items-center gap-2">
        <span className="h-3 w-1 shrink-0 rounded-full bg-(--color-value)" />
        <span className="text-sm font-semibold tabular text-popover-foreground">
          {formatValue
            ? formatValue(Number(item.value), String(item.dataKey))
            : formatNumber(Number(item.value))}
        </span>
      </div>
      <span className="max-w-64 text-muted-foreground">
        {formatLabel ? formatLabel(name) : name}
      </span>
    </div>
  );
}

/** Several series' tooltip: what the point is, then each series' value in its color. */
export function MultiTooltip({
  active,
  payload,
  label,
  formatLabel,
  formatValue,
  order,
}: Props & { order?: (item: { dataKey?: unknown }) => number }) {
  if (!active || !payload?.length) return null;
  const name = String(label ?? "");
  const items = order ? payload.toSorted((a, b) => order(a) - order(b)) : payload;
  return (
    <div className="grid min-w-36 gap-1 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <span className="max-w-64 text-muted-foreground">
        {formatLabel ? formatLabel(name) : name}
      </span>
      {items.map((item) => (
        <div key={String(item.dataKey)} className="flex items-center gap-2">
          <span className="h-3 w-1 shrink-0 rounded-full" style={{ background: item.color }} />
          <span className="text-popover-foreground">{item.name}</span>
          <span className="ml-auto pl-4 text-sm font-semibold tabular text-popover-foreground">
            {item.value === null || item.value === undefined
              ? "—"
              : formatValue
                ? formatValue(Number(item.value), String(item.dataKey))
                : formatNumber(Number(item.value))}
          </span>
        </div>
      ))}
    </div>
  );
}
