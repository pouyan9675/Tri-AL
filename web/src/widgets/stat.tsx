/**
 * Stat tiles: one per row, its label and its value. A row's own `format` key ("percent")
 * overrides the chart's; a missing value shows as "—".
 */
import {
  Activity,
  CalendarClock,
  CircleCheck,
  DoorOpen,
  Globe2,
  HeartCrack,
  type LucideIcon,
  Pill,
  Sigma,
  Syringe,
  TestTubes,
  TriangleAlert,
  UserRound,
  Users,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import type { NumberFormat } from "@/lib/format";
import { cn } from "@/lib/utils";
import { formatted, points, type WidgetProps } from "./common";

/** Icons for the tiles the bundled plugins send; any other tile gets a generic one. */
const ICONS: Record<string, LucideIcon> = {
  trials: TestTubes,
  interventions: Syringe,
  drugs: Pill,
  conditions: Activity,
  countries: Globe2,
  participants: Users,
  at_risk: Users,
  women: UserRound,
  age: CalendarClock,
  completed: CircleCheck,
  serious: TriangleAlert,
  deaths: HeartCrack,
  left: DoorOpen,
};

export function StatWidget({ spec, rows }: WidgetProps) {
  const tiles = points({ ...spec, x: spec.x || "label" }, rows);
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-3 sm:gap-4 @xl:grid-cols-3",
        tiles.length >= 5 ? "@4xl:grid-cols-5" : "@4xl:grid-cols-4",
      )}
    >
      {tiles.map((tile, index) => {
        const key = String(tile.row.key ?? tile.label);
        const Icon = ICONS[key] ?? Sigma;
        return (
          <Card
            key={key}
            size="sm"
            className={cn(
              "gap-1 px-4 py-3.5 shadow-xs",
              index === 0 && tiles.length % 2 === 1 && "col-span-2 @xl:col-span-1",
            )}
          >
            <div className="flex items-center justify-between gap-2 text-muted-foreground">
              <span className="truncate text-[0.8rem] font-medium">{tile.label}</span>
              <Icon className="size-4 shrink-0 opacity-70" />
            </div>
            <div className="text-2xl font-semibold tracking-tight tabular sm:text-[1.7rem]">
              {formatted(
                tile.row[spec.y],
                tile.row.format === "percent" || tile.row.format === "number"
                  ? (tile.row.format as NumberFormat)
                  : spec.format,
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}
