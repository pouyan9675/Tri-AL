import type { TooltipContentProps } from "recharts";
import { formatNumber } from "@/lib/format";

type Props = Partial<TooltipContentProps<number, string>> & {
  formatLabel?: (label: string) => string;
};

/** One series' tooltip: the value first and strong, then what it's for. */
export function SingleTooltip({ active, payload, label, formatLabel }: Props) {
  const item = payload?.[0];
  if (!active || !item) return null;
  const name = String(label ?? item.payload?.label ?? "");
  return (
    <div className="grid min-w-28 gap-0.5 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <div className="flex items-center gap-2">
        <span className="h-3 w-1 shrink-0 rounded-full bg-(--color-value)" />
        <span className="text-sm font-semibold tabular text-popover-foreground">
          {formatNumber(Number(item.value))}
        </span>
      </div>
      <span className="max-w-64 text-muted-foreground">
        {formatLabel ? formatLabel(name) : name}
      </span>
    </div>
  );
}
