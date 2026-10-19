/**
 * The widget registry: a chart spec's `widget` names the component that draws it. Plugins add
 * charts as specs on the server (`registry.add_chart`), so a new chart needs no front-end code
 * as long as its widget type is one of these. An unknown type gets a placeholder.
 */
import { type ComponentType, lazy } from "react";
import { BarWidget } from "./bar";
import type { WidgetProps } from "./common";
import { PieWidget } from "./pie";
import { ScatterWidget } from "./scatter";
import { AreaWidget, LineWidget } from "./series";
import { StatWidget } from "./stat";
import { TableWidget } from "./table";
import { TrendsWidget } from "./trends";

export type WidgetDefinition = {
  component: ComponentType<WidgetProps>;
  /** False: the widget draws its own cards (stat tiles), with no card around it. */
  card: boolean;
  /** Whether a table view of the same rows is offered. */
  table: boolean;
};

const MapWidget = lazy(() => import("./map"));
// three.js and the scene: only the analysis page draws one.
const Scatter3DWidget = lazy(() => import("./scatter3d"));

export const WIDGETS: Record<string, WidgetDefinition> = {
  stat: { component: StatWidget, card: false, table: false },
  bar: { component: BarWidget, card: true, table: true },
  line: { component: LineWidget, card: true, table: true },
  area: { component: AreaWidget, card: true, table: true },
  pie: { component: PieWidget, card: true, table: true },
  table: { component: TableWidget, card: true, table: false },
  map: { component: MapWidget, card: true, table: true },
  trends: { component: TrendsWidget, card: true, table: false },
  scatter: { component: ScatterWidget, card: true, table: false },
  scatter3d: { component: Scatter3DWidget, card: true, table: false },
};

export function widgetFor(type: string): WidgetDefinition | undefined {
  return Object.hasOwn(WIDGETS, type) ? WIDGETS[type] : undefined;
}
