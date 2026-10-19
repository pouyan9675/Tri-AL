/**
 * The map of recent trials: UMAP coordinates, one dot per trial. Only the largest clusters on
 * the whole map get a colour (the row's `color`, 0 to 7, the same under every filter); the
 * rest are grey, and trials in no cluster fainter still, drawn underneath. A toggle narrows it
 * to the last few months (the summary's `windows`): those trials in colour, the rest of the
 * year faint behind them, on the same axes. Drawn on a canvas (`scatter-canvas.ts`): as SVG,
 * the 3,000 dots held up the dashboard's first load.
 */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type CSSProperties, type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { chartQuery } from "@/api/queries";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { TrialFilter } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { WidgetProps } from "./common";
import { type Dots, type Hit, LandscapeCanvas, readColors } from "./scatter-canvas";
import { FAINT, GHOST, GREY } from "./scatter3d-points";

type Point = {
  x: number;
  y: number;
  cluster: number;
  cluster_label: string;
  cluster_size: number;
  color: number | null;
  title: string;
  source_id: string;
};

export type Summary = {
  status: string;
  total_trials: number;
  embedded_trials: number;
  plotted_trials: number;
  clusters: number;
  noise_trials: number;
  since?: string;
  until?: string;
  model: string;
  dimensions?: number;
  /** The recent windows, then the whole map: `since` is the first_posted filter for each. */
  windows?: { months: number; since: string }[];
};

const color = (point: Pick<Point, "color">) =>
  point.color === null || point.color === undefined
    ? "var(--muted-foreground)"
    : `var(--chart-${point.color + 1})`;

function isPoint(row: Record<string, unknown>): row is Record<string, unknown> & Point {
  return row.type === "point" && typeof row.x === "number" && typeof row.y === "number";
}

function PointTooltip({ point, style }: { point: Point; style: CSSProperties }) {
  return (
    <div
      className="pointer-events-none absolute z-10 w-max max-w-xs rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md"
      style={style}
      role="tooltip"
    >
      <div className="font-medium leading-snug">{point.title}</div>
      <div className="mt-1 text-xs text-muted-foreground">{point.source_id}</div>
      <div className="mt-2 flex items-center gap-2 text-xs">
        <span className="size-2 rounded-full" style={{ background: color(point) }} />
        <span>{point.cluster_label}</span>
        <span className="text-muted-foreground">{formatNumber(point.cluster_size)} trials</span>
      </div>
      <div className="mt-2 text-[11px] text-muted-foreground">Click to open the trial</div>
    </div>
  );
}

export function ScatterWidget({ spec, rows, height, filter = {} }: WidgetProps) {
  const summary = rows.find((row) => row.type === "summary") as Summary | undefined;
  const windows = summary?.windows ?? [];
  const whole = windows.at(-1);
  const [months, setMonths] = useState<number | null>(null);
  const current = windows.find((w) => w.months === months) ?? whole;
  const narrowed = current !== undefined && whole !== undefined && current.months < whole.months;
  // A window is the same chart under a first_posted filter: its own sample of the same map.
  const recent = useQuery({
    ...chartQuery(spec.id, current ? postedSince(filter, current.since) : filter),
    enabled: narrowed,
  });
  const shownRows = narrowed ? (recent.data?.rows ?? []) : rows;
  const shown = (shownRows.find((row) => row.type === "summary") as Summary | undefined) ?? summary;
  const points = useMemo(() => shownRows.filter(isPoint), [shownRows]);
  // With a window, the rest of the year stays behind it in faint grey, and keeps the axes.
  const year = useMemo(() => (narrowed ? rows.filter(isPoint) : []), [narrowed, rows]);
  const drawn = useMemo(() => buildDots(points, year), [points, year]);
  const legend = useMemo(() => legendOf(points), [points]);

  if (summary?.status !== "ready" || !shown) {
    return <LandscapeUnavailable status={summary?.status} />;
  }

  return (
    <div className="flex flex-col gap-3" data-testid="landscape">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            <span className="font-medium text-foreground tabular">
              {formatNumber(shown.embedded_trials)}
            </span>{" "}
            {shown.embedded_trials === 1 ? "trial" : "trials"} first posted{" "}
            {formatDate(current?.since ?? shown.since)} – {formatDate(shown.until)}
            {narrowed && recent.isFetching && !recent.data ? " (loading…)" : ""}
          </span>
          <span>{formatNumber(shown.clusters)} clusters</span>
          {shown.plotted_trials < shown.embedded_trials && (
            <span>{formatNumber(shown.plotted_trials)} drawn</span>
          )}
          <span title={shown.model}>{shown.dimensions}-dimensional vectors</span>
        </div>
        {windows.length > 1 && (
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={String(current?.months)}
            onValueChange={(value) => value && setMonths(Number(value))}
            aria-label="Trials from the last"
          >
            {windows.map((w) => (
              <ToggleGroupItem key={w.months} value={String(w.months)} className="px-2.5 text-xs">
                {w.months} months
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>
      <Plot drawn={drawn} height={Math.max(260, height - 74)} />
      <ul className="flex flex-wrap gap-x-4 gap-y-2" aria-label="Cluster legend">
        {legend.colored.map((item) => (
          <li key={item.cluster} className="flex min-w-0 items-center gap-1.5 text-xs">
            <span className="size-2.5 shrink-0 rounded-full" style={{ background: color(item) }} />
            <span className="max-w-44 truncate" title={item.label}>
              {item.label}
            </span>
            <span className="text-muted-foreground">{formatNumber(item.size)}</span>
          </li>
        ))}
        {legend.other.clusters > 0 && (
          <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="size-2.5 shrink-0 rounded-full bg-muted-foreground/40" />
            {formatNumber(legend.other.clusters)} smaller clusters ·{" "}
            {formatNumber(legend.other.trials)}
          </li>
        )}
        {legend.unclustered > 0 && (
          <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="size-2.5 shrink-0 rounded-full bg-muted-foreground/20" />
            In no cluster · {formatNumber(legend.unclustered)}
          </li>
        )}
        {narrowed && (
          <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="size-2.5 shrink-0 rounded-full bg-muted-foreground/10 ring-1 ring-muted-foreground/30" />
            Earlier in the year
          </li>
        )}
      </ul>
    </div>
  );
}

const UNAVAILABLE: Record<string, { title: string; detail: string }> = {
  missing_embeddings: {
    title: "Embed the trials to build this map",
    detail:
      "Run `tri-al embeddings generate` (about five minutes for every trial); the page updates when it finishes. Each update embeds its new and changed trials.",
  },
  missing_layout: {
    title: "Rebuild the stats to lay out this map",
    detail:
      "The map was laid out before this view existed. Run `tri-al stats` (a minute or two); the page updates when it finishes, and each update keeps it current.",
  },
  disabled: {
    title: "This map is turned off",
    detail:
      "Set `cluster_3d = true` under `[plugins.insights]` in tri-al.toml, then run `tri-al stats`.",
  },
};

/** Why a map of the landscape can't be drawn (a summary row's `status`), and what to do. */
export function LandscapeUnavailable({ status }: { status: string | undefined }) {
  const reason = (status && UNAVAILABLE[status]) || {
    title: "Not enough trials to cluster",
    detail: "The map needs at least three recent trials with vectors.",
  };
  return (
    <div
      className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed px-6 text-center"
      data-testid="landscape-unavailable"
    >
      <div className="font-medium">{reason.title}</div>
      <div className="mt-2 max-w-lg text-sm text-muted-foreground">{reason.detail}</div>
    </div>
  );
}

type Drawn = Dots & {
  /** The trial each dot is, by index; null for the faint year behind a window. */
  trials: (Point | null)[];
};

const slotOf = (point: Point) =>
  point.color != null && point.color >= 0 && point.color < GREY
    ? point.color
    : point.cluster < 0
      ? FAINT
      : GREY;
const rank = (slot: number) => (slot === GHOST ? 0 : slot === FAINT ? 1 : slot === GREY ? 2 : 3);

/**
 * The dots in drawing order: the year behind a window, then trials in no cluster, the grey
 * clusters, and the coloured clusters last, on top.
 */
export function buildDots(points: Point[], behind: Point[] = []): Drawn {
  const ordered = [
    ...behind.map((point) => ({ point, slot: GHOST })),
    ...points.map((point) => ({ point, slot: slotOf(point) })),
  ].sort((a, b) => rank(a.slot) - rank(b.slot) || b.point.cluster - a.point.cluster);
  const xs = new Float64Array(ordered.length);
  const ys = new Float64Array(ordered.length);
  const slots = new Uint8Array(ordered.length);
  const trials: (Point | null)[] = [];
  ordered.forEach(({ point, slot }, i) => {
    xs[i] = point.x;
    ys[i] = point.y;
    slots[i] = slot;
    trials.push(slot === GHOST ? null : point);
  });
  return { xs, ys, slots, trials };
}

/** The dots on a canvas, with the trial under the pointer named; a click opens it. */
function Plot({ drawn, height }: { drawn: Drawn; height: number }) {
  const navigate = useNavigate();
  const frameRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [plot, setPlot] = useState<LandscapeCanvas | null>(null);
  // The dot under the pointer, for the dots it was found in (a window changes them).
  const [hover, setHover] = useState<{ hit: Hit; drawn: Drawn } | null>(null);
  const hit = hover?.drawn === drawn ? hover.hit : null;
  const hovered = hit ? drawn.trials[hit.index] : null;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const made = new LandscapeCanvas(canvas);
    const resize = new ResizeObserver(([entry]) => {
      if (entry) made.resize(entry.contentRect.width, entry.contentRect.height);
    });
    resize.observe(canvas);
    const rect = canvas.getBoundingClientRect();
    made.resize(rect.width, rect.height);
    // The theme's colours, again whenever the theme changes the class on <html>.
    made.setColors(readColors(canvas));
    const theme = new MutationObserver(() => made.setColors(readColors(canvas)));
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    setPlot(made);
    return () => {
      resize.disconnect();
      theme.disconnect();
      setPlot(null);
    };
  }, []);

  useEffect(() => {
    plot?.setDots(drawn);
  }, [plot, drawn]);

  const pick = (event: MouseEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return plot?.pick(event.clientX - rect.left, event.clientY - rect.top) ?? null;
  };

  return (
    <div ref={frameRef} className="relative w-full" style={{ height }}>
      <canvas
        ref={canvasRef}
        className={cn("block size-full", hovered && "cursor-pointer")}
        role="img"
        aria-label={`Trials placed by what they're about: ${formatNumber(drawn.trials.filter(Boolean).length)} dots`}
        data-testid="landscape-canvas"
        onPointerMove={(event) => {
          const found = pick(event);
          if (found?.index !== hit?.index) setHover(found && { hit: found, drawn });
        }}
        onPointerLeave={() => setHover(null)}
        onClick={(event) => {
          const found = pick(event);
          const point = found ? drawn.trials[found.index] : null;
          if (point)
            void navigate({ to: "/trials/$sourceId", params: { sourceId: point.source_id } });
        }}
      />
      {hit && hovered && (
        <>
          <span
            className="pointer-events-none absolute size-2.5 -translate-1/2 rounded-full border-[1.5px] border-foreground"
            style={{ left: hit.x, top: hit.y }}
          />
          <PointTooltip point={hovered} style={tooltipPlace(hit, frameRef.current)} />
        </>
      )}
    </div>
  );
}

/** Beside the dot, flipped to stay inside the plot. */
function tooltipPlace(hit: Hit, frame: HTMLElement | null): CSSProperties {
  const width = frame?.clientWidth ?? 0;
  const height = frame?.clientHeight ?? 0;
  const style: CSSProperties = {};
  if (hit.x > width - 330) style.right = width - hit.x + 12;
  else style.left = hit.x + 12;
  if (hit.y > height - 140) style.bottom = height - hit.y + 12;
  else style.top = hit.y + 12;
  return style;
}

/** ``filter`` with trials first posted from ``since`` on, inside its own first_posted range. */
export function postedSince(filter: TrialFilter, since: string): TrialFilter {
  const [from = "", to = ""] = (filter.first_posted ?? "..").split("..");
  return { ...filter, first_posted: `${from > since ? from : since}..${to}` };
}

type LegendItem = { cluster: number; label: string; size: number; color: number };

/** The coloured clusters in colour order, then what the grey dots stand for. */
export function legendOf(points: Point[]) {
  const seen = new Map<number, Point>();
  for (const point of points) seen.set(point.cluster, point);
  const colored: LegendItem[] = [];
  const other = { clusters: 0, trials: 0 };
  let unclustered = 0;
  for (const point of seen.values()) {
    if (point.color != null) {
      colored.push({
        cluster: point.cluster,
        label: point.cluster_label,
        size: point.cluster_size,
        color: point.color,
      });
    } else if (point.cluster < 0) {
      unclustered = point.cluster_size;
    } else {
      other.clusters += 1;
      other.trials += point.cluster_size;
    }
  }
  colored.sort((a, b) => a.color - b.color);
  return { colored, other, unclustered };
}
