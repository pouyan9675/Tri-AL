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
import type { WidgetProps } from "./common";

const HIDDEN = new Set(["key"]);

export function TableWidget({ spec, rows, height }: WidgetProps) {
  const columns = useMemo(() => {
    const keys = new Set<string>();
    for (const row of rows) for (const key of Object.keys(row)) keys.add(key);
    keys.delete(spec.x);
    keys.delete(spec.y);
    return [spec.x, ...[...keys].filter((key) => !HIDDEN.has(key)), spec.y];
  }, [rows, spec.x, spec.y]);

  return (
    <div className="overflow-auto rounded-lg border" style={{ maxHeight: Math.max(height, 240) }}>
      <Table>
        <TableHeader className="sticky top-0 bg-card">
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column} className={cn(column === spec.y && "text-right")}>
                {humanize(column)}
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
                return (
                  <TableCell
                    key={column}
                    className={cn(typeof value === "number" && "text-right tabular")}
                  >
                    {typeof value === "number"
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
