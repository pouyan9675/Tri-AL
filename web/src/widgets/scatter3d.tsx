/**
 * The research landscape in 3-D: each recent trial placed by its embedding (UMAP to three
 * dimensions on the server), drawn with WebGL in a lazy chunk with three.js. Clusters and
 * colours are the dashboard map's: the 8 largest on the whole map in colour, the rest grey,
 * trials in no cluster fainter. Drag to turn it, scroll to zoom; hovering a trial names it,
 * clicking pins it with a link, and choosing a cluster in the list lights it up. Under a
 * filter or a recent window, the whole map stays behind the matching trials, faint.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Pause, Play, RotateCcw, X } from "lucide-react";
import {
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ChartRow } from "@/api/client";
import { chartQuery } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { activeCount } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { WidgetProps } from "./common";
import { LandscapeUnavailable, postedSince, type Summary } from "./scatter";
import { type Cloud, FAINT, GHOST, GREY, NO_CLUSTER, readPalette } from "./scatter3d-points";
import { LandscapeScene } from "./scatter3d-scene";

export type ClusterRow = { cluster: number; label: string; size: number; color: number | null };
export type PointRow = {
  x: number;
  y: number;
  z: number;
  cluster: number;
  title: string;
  source_id: string;
};
export type Landscape = { summary?: Summary; clusters: ClusterRow[]; points: PointRow[] };

/** A press that moves less than this (px) is a click, not a turn of the view. */
const CLICK_SLOP = 4;
const ZOOM_KEY =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘" : "Ctrl";

export function parseLandscape(rows: ChartRow[]): Landscape {
  const result: Landscape = { clusters: [], points: [] };
  for (const row of rows) {
    if (row.type === "summary") result.summary = row as unknown as Summary;
    else if (row.type === "cluster") result.clusters.push(row as unknown as ClusterRow);
    else if (
      row.type === "point" &&
      typeof row.x === "number" &&
      typeof row.y === "number" &&
      typeof row.z === "number"
    ) {
      result.points.push(row as unknown as PointRow);
    }
  }
  return result;
}

export type Drawn = {
  cloud: Cloud;
  /** The trial each drawn point is, by index; null for the faint context behind a filter. */
  trials: (PointRow | null)[];
  index: Map<string, number>;
};

/**
 * The points in drawing order: the context first, then trials in no cluster, grey clusters,
 * and the coloured clusters last, on top. Context trials that are also shown are left out.
 */
export function buildCloud(
  points: PointRow[],
  clusters: ClusterRow[],
  context: PointRow[] | null = null,
): Drawn {
  const colors = new Map(clusters.map((c) => [c.cluster, c.color]));
  const slotOf = (point: PointRow) => {
    if (point.cluster < 0) return FAINT;
    const color = colors.get(point.cluster);
    return color === null || color === undefined ? GREY : color;
  };
  const rank = (slot: number) => (slot === FAINT ? 0 : slot === GREY ? 1 : 2);
  const shown = new Set(points.map((p) => p.source_id));
  const behind = (context ?? []).filter((p) => !shown.has(p.source_id));
  const ordered = points
    .map((point) => ({ point, slot: slotOf(point) }))
    .sort((a, b) => rank(a.slot) - rank(b.slot) || b.slot - a.slot);

  const count = behind.length + ordered.length;
  const positions = new Float32Array(count * 3);
  const slots = new Uint8Array(count);
  const ids = new Int32Array(count);
  const trials: (PointRow | null)[] = [];
  const index = new Map<string, number>();
  let i = 0;
  for (const point of behind) {
    positions.set([point.x, point.y, point.z], i * 3);
    slots[i] = GHOST;
    ids[i] = NO_CLUSTER;
    trials.push(null);
    i++;
  }
  for (const { point, slot } of ordered) {
    positions.set([point.x, point.y, point.z], i * 3);
    slots[i] = slot;
    ids[i] = point.cluster;
    trials.push(point);
    index.set(point.source_id, i);
    i++;
  }
  return { cloud: { positions, slots, clusters: ids }, trials, index };
}

const swatch = (color: number | null | undefined, cluster: number) =>
  color !== null && color !== undefined
    ? `var(--chart-${color + 1})`
    : cluster < 0
      ? "color-mix(in oklab, var(--muted-foreground) 35%, transparent)"
      : "color-mix(in oklab, var(--muted-foreground) 70%, transparent)";

function reducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function Scatter3DWidget({ spec, rows, height, filter = {} }: WidgetProps) {
  const base = useMemo(() => parseLandscape(rows), [rows]);
  const windows = base.summary?.windows ?? [];
  const whole = windows.at(-1);
  const [months, setMonths] = useState<number | null>(null);
  const current = windows.find((w) => w.months === months) ?? whole;
  const narrowed = current !== undefined && whole !== undefined && current.months < whole.months;
  const filtered = activeCount(filter) > 0;
  // A window is the same chart under a first_posted filter, as on the dashboard's map.
  const recent = useQuery({
    ...chartQuery(spec.id, current ? postedSince(filter, current.since) : filter),
    enabled: narrowed,
  });
  // Under a filter or a window, the whole map (precomputed, unfiltered) stays behind, faint.
  const everything = useQuery({ ...chartQuery(spec.id, {}), enabled: filtered || narrowed });
  const focus = useMemo(
    () => (narrowed ? (recent.data ? parseLandscape(recent.data.rows) : null) : base),
    [narrowed, recent.data, base],
  );
  const context = useMemo(
    () =>
      (filtered || narrowed) && everything.data
        ? parseLandscape(everything.data.rows).points
        : null,
    [filtered, narrowed, everything.data],
  );
  const shown = focus ?? base;
  const drawn = useMemo(() => buildCloud(shown.points, shown.clusters, context), [shown, context]);

  if (base.summary?.status !== "ready") {
    return <LandscapeUnavailable status={base.summary?.status} />;
  }

  const summary = shown.summary ?? base.summary;
  return (
    <div className="@container flex flex-col gap-3" data-testid="landscape-3d">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            <span className="font-medium text-foreground tabular">
              {formatNumber(summary.embedded_trials)}
            </span>{" "}
            {summary.embedded_trials === 1 ? "trial" : "trials"} first posted{" "}
            {formatDate(current?.since ?? summary.since)} – {formatDate(summary.until)}
            {narrowed && recent.isFetching && !recent.data ? " (loading…)" : ""}
          </span>
          <span>{formatNumber(summary.clusters)} clusters</span>
          {summary.plotted_trials < summary.embedded_trials && (
            <span>{formatNumber(summary.plotted_trials)} drawn</span>
          )}
          <span title={summary.model}>{summary.dimensions}-dimensional vectors</span>
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
      <Viewer
        drawn={drawn}
        clusters={shown.clusters}
        height={Math.max(380, height - 70)}
        behind={context !== null}
      />
    </div>
  );
}

type Hover = { index: number; x: number; y: number };

function Viewer({
  drawn,
  clusters,
  height,
  behind,
}: {
  drawn: Drawn;
  clusters: ClusterRow[];
  height: number;
  behind: boolean;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState<LandscapeScene | null>(null);
  const [failed, setFailed] = useState(false);
  const [rotating, setRotating] = useState(() => !reducedMotion());
  const [hover, setHover] = useState<Hover | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<number | null>(null);
  const [zoomHint, setZoomHint] = useState(false);
  const pointer = useRef<{ x: number; y: number; down: { x: number; y: number } | null } | null>(
    null,
  );
  const frame = useRef(0);

  const colors = useMemo(() => new Map(clusters.map((c) => [c.cluster, c])), [clusters]);
  // A filter can leave the highlighted cluster or the pinned trial out.
  const lit = highlight !== null && colors.has(highlight) ? highlight : null;
  const pinnedIndex = selected === null ? undefined : drawn.index.get(selected);
  const pinned = pinnedIndex === undefined ? null : drawn.trials[pinnedIndex];
  const hovered = hover ? drawn.trials[hover.index] : null;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    // A canvas of its own each time: a context given back can't be had again from the same one.
    const canvas = document.createElement("canvas");
    canvas.className = "block size-full";
    host.append(canvas);
    let made: LandscapeScene;
    try {
      made = new LandscapeScene(canvas);
    } catch {
      canvas.remove();
      setFailed(true);
      return;
    }
    made.onInteract = () => setRotating(false);
    let hintTimer = 0;
    made.onScroll = () => {
      setZoomHint(true);
      clearTimeout(hintTimer);
      hintTimer = window.setTimeout(() => setZoomHint(false), 1500);
    };
    const resize = new ResizeObserver(([entry]) => {
      if (entry) made.resize(entry.contentRect.width, entry.contentRect.height);
    });
    resize.observe(host);
    const rect = host.getBoundingClientRect();
    made.resize(rect.width, rect.height);
    // The theme's colours, again whenever the theme changes the class on <html>.
    made.setPalette(readPalette(host));
    const theme = new MutationObserver(() => made.setPalette(readPalette(host)));
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    // Draw only while on screen.
    const visible =
      typeof IntersectionObserver === "function"
        ? new IntersectionObserver(([entry]) =>
            entry?.isIntersecting ? made.start() : made.stop(),
          )
        : null;
    if (visible) visible.observe(host);
    else made.start();
    setScene(made);
    return () => {
      clearTimeout(hintTimer);
      resize.disconnect();
      theme.disconnect();
      visible?.disconnect();
      made.dispose();
      canvas.remove();
      setScene(null);
    };
  }, []);

  const repick = useCallback(() => {
    const at = pointer.current;
    if (!scene || !at || at.down) return;
    const index = scene.pick(at.x, at.y);
    setHover((previous) =>
      index === null
        ? null
        : previous?.index === index
          ? { ...previous, x: at.x, y: at.y }
          : { index, x: at.x, y: at.y },
    );
  }, [scene]);

  useEffect(() => {
    if (scene) scene.onFrame = repick;
  }, [scene, repick]);

  useEffect(() => {
    scene?.setCloud(drawn.cloud);
  }, [scene, drawn]);

  useEffect(() => {
    scene?.setHighlight(lit);
  }, [scene, lit]);

  useEffect(() => {
    scene?.setMarked(hover?.index ?? pinnedIndex ?? null);
  }, [scene, hover, pinnedIndex]);

  useEffect(() => {
    scene?.setAutoRotate(rotating);
  }, [scene, rotating]);

  // Escape lets go of the pinned trial and the lit cluster.
  const holding = pinned !== null || lit !== null;
  useEffect(() => {
    if (!holding) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelected(null);
      setHighlight(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [holding]);

  const position = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const at = position(event);
    const down = pointer.current?.down ?? null;
    pointer.current = { ...at, down };
    if (down) {
      if (Math.hypot(at.x - down.x, at.y - down.y) > CLICK_SLOP) setHover(null);
      return;
    }
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(repick);
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const at = position(event);
    const down = pointer.current?.down;
    pointer.current = { ...at, down: null };
    if (!down || !scene || Math.hypot(at.x - down.x, at.y - down.y) > CLICK_SLOP) return;
    const index = scene.pick(at.x, at.y);
    setSelected(index === null ? null : (drawn.trials[index]?.source_id ?? null));
  };

  if (failed) {
    return (
      <div
        className="flex flex-col items-center justify-center rounded-lg border border-dashed px-6 text-center"
        style={{ height }}
      >
        <div className="font-medium">This browser can't draw the 3D map</div>
        <div className="mt-2 max-w-md text-sm text-muted-foreground">
          WebGL is turned off or unavailable. The dashboard's map shows the same clusters in 2D.
        </div>
        <Button asChild variant="outline" size="sm" className="mt-4">
          <Link to="/">Open the dashboard</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-3 @3xl:grid-cols-[minmax(0,1fr)_15rem]">
      <div
        ref={frameRef}
        className="relative max-h-[min(75svh,110cqw)] min-h-80 overflow-hidden rounded-lg border bg-muted/20"
        style={{ height }}
      >
        <div
          ref={hostRef}
          className={cn("absolute inset-0 touch-none", hovered && "cursor-pointer")}
          role="img"
          aria-label={`Trials in three dimensions: ${formatNumber(drawn.index.size)} points in ${formatNumber(clusters.filter((c) => c.cluster >= 0).length)} clusters`}
          data-testid="landscape-3d-canvas"
          onPointerDown={(event) => {
            const at = position(event);
            pointer.current = { ...at, down: at };
          }}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => {
            pointer.current = null;
            cancelAnimationFrame(frame.current);
            setHover(null);
          }}
        />
        <div className="absolute top-2 right-2 flex gap-1">
          <IconButton
            label={rotating ? "Stop turning" : "Turn slowly"}
            onClick={() => setRotating(!rotating)}
          >
            {rotating ? <Pause /> : <Play />}
          </IconButton>
          <IconButton label="Reset the view" onClick={() => scene?.resetView()}>
            <RotateCcw />
          </IconButton>
        </div>
        {pinned && (
          <div
            className="absolute top-2 left-2 w-[min(22rem,calc(100%-6rem))] rounded-lg border bg-popover/95 p-3 text-popover-foreground shadow-md backdrop-blur-sm"
            data-testid="pinned-trial"
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1 text-sm leading-snug font-medium">{pinned.title}</div>
              <Button
                variant="ghost"
                size="icon-sm"
                className="-mt-1 -mr-1 shrink-0 text-muted-foreground"
                aria-label="Close"
                onClick={() => setSelected(null)}
              >
                <X />
              </Button>
            </div>
            <ClusterLine point={pinned} cluster={colors.get(pinned.cluster)} />
            <Button asChild size="sm" variant="outline" className="mt-3 h-7 text-xs">
              <Link to="/trials/$sourceId" params={{ sourceId: pinned.source_id }}>
                Open {pinned.source_id}
                <ArrowRight />
              </Link>
            </Button>
          </div>
        )}
        {hovered && hover && hovered.source_id !== pinned?.source_id && (
          <div
            className="pointer-events-none absolute z-10 max-w-xs rounded-lg border bg-popover px-3 py-2 text-popover-foreground shadow-md"
            style={tooltipPlace(hover, frameRef.current)}
            role="tooltip"
          >
            <div className="text-sm leading-snug font-medium">{hovered.title}</div>
            <ClusterLine point={hovered} cluster={colors.get(hovered.cluster)} />
            <div className="mt-2 text-[11px] text-muted-foreground">Click to pin</div>
          </div>
        )}
        <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-muted-foreground">
          Drag to turn · pinch or {ZOOM_KEY} + scroll to zoom · right-drag to move
        </div>
        {zoomHint && (
          <div className="pointer-events-none absolute inset-x-0 bottom-10 flex justify-center">
            <div className="rounded-md bg-foreground/85 px-3 py-1.5 text-xs text-background shadow">
              To zoom, pinch or hold {ZOOM_KEY} while scrolling
            </div>
          </div>
        )}
      </div>
      <ClusterList
        clusters={clusters}
        lit={lit}
        onToggle={(cluster) => setHighlight(lit === cluster ? null : cluster)}
        behind={behind}
        height={height}
      />
    </div>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size="icon-sm"
          className="bg-background/80 backdrop-blur-sm"
          aria-label={label}
          onClick={onClick}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function ClusterLine({ point, cluster }: { point: PointRow; cluster: ClusterRow | undefined }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className="font-mono text-muted-foreground">{point.source_id}</span>
      <span className="flex min-w-0 items-center gap-1.5">
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ background: swatch(cluster?.color, point.cluster) }}
        />
        <span className="truncate">
          {point.cluster < 0 ? "In no cluster" : (cluster?.label ?? `Cluster ${point.cluster + 1}`)}
        </span>
      </span>
    </div>
  );
}

function ClusterList({
  clusters,
  lit,
  onToggle,
  behind,
  height,
}: {
  clusters: ClusterRow[];
  lit: number | null;
  onToggle: (cluster: number) => void;
  behind: boolean;
  height: number;
}) {
  return (
    <div
      className="flex min-h-0 flex-col gap-2 @3xl:max-h-(--list-height)"
      style={{ "--list-height": `${height}px` } as CSSProperties}
    >
      <div className="flex items-baseline justify-between gap-2 px-1 text-xs text-muted-foreground">
        <span>Clusters · choose one to light it up</span>
      </div>
      <ul
        className="flex max-h-64 min-h-0 flex-col gap-0.5 overflow-y-auto @3xl:max-h-none"
        aria-label="Clusters"
      >
        {clusters.map((cluster) => (
          <li key={cluster.cluster}>
            <button
              type="button"
              aria-pressed={lit === cluster.cluster}
              onClick={() => onToggle(cluster.cluster)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                lit === cluster.cluster && "bg-muted font-medium",
                lit !== null && lit !== cluster.cluster && "text-muted-foreground",
              )}
            >
              <span
                className="size-2.5 shrink-0 rounded-full"
                style={{ background: swatch(cluster.color, cluster.cluster) }}
              />
              <span className="min-w-0 flex-1 truncate" title={cluster.label}>
                {cluster.cluster < 0 ? "In no cluster" : cluster.label}
              </span>
              <span className="text-muted-foreground tabular">{formatNumber(cluster.size)}</span>
            </button>
          </li>
        ))}
        {behind && (
          <li className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground">
            <span className="size-2.5 shrink-0 rounded-full bg-muted-foreground/10 ring-1 ring-muted-foreground/30" />
            The rest of the map
          </li>
        )}
      </ul>
    </div>
  );
}

/** Beside the pointer, flipped to stay inside the frame. */
function tooltipPlace(hover: Hover, frame: HTMLElement | null): CSSProperties {
  const width = frame?.clientWidth ?? 0;
  const height = frame?.clientHeight ?? 0;
  const style: CSSProperties = {};
  if (hover.x > width - 300) style.right = width - hover.x + 14;
  else style.left = hover.x + 14;
  if (hover.y > height - 140) style.bottom = height - hover.y + 14;
  else style.top = hover.y + 14;
  return style;
}
