/** Rows as a table: every key of the rows becomes a column. Also every chart's table view. */
import { useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatNumber, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { formatted, seriesOf, type WidgetProps } from "./common";

const HIDDEN = new Set(["key", "format"]);

export function TableWidget({ spec, rows, height }: WidgetProps) {
  const { columns, numbers, names } = useMemo(() => {
    const series = seriesOf(spec);
    const keys = new Set<string>();
    for (const row of rows) for (const key of Object.keys(row)) keys.add(key);
    keys.delete(spec.x);
    for (const one of series) keys.delete(one.key);
    return {
      columns: [
        spec.x,
        ...[...keys].filter((key) => !HIDDEN.has(key)),
        ...series.map((s) => s.key),
      ],
      // Each number column reads as its series does.
      numbers: new Map(series.map((one) => [one.key, one.format])),
      names: new Map(spec.series.map((one) => [one.key, one.label])),
    };
  }, [rows, spec]);

  return (
    <div className="overflow-auto rounded-lg border" style={{ maxHeight: Math.max(height, 240) }}>
      <Table>
        <TableHeader className="sticky top-0 bg-card">
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column} className={cn(numbers.has(column) && "text-right")}>
                {names.get(column) ?? humanize(column)}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows have no id of their own
            <TableRow key={index}>
              {columns.map((column) => {
                const value = row[column];
                const format = numbers.get(column);
                return (
                  <TableCell
                    key={column}
                    className={cn((typeof value === "number" || format) && "text-right tabular")}
                  >
                    {format
                      ? formatted(value, format)
                      : typeof value === "number"
                        ? formatNumber(value)
                        : value === null
                          ? "—"
                          : String(value ?? "")}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
