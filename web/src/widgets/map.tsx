/**
 * The `map` widget: a choropleth of rows keyed by ISO 3166-1 alpha-2 code (`x`), in its own
 * lazily loaded chunk.
 *
 * Drawn as SVG with d3-geo (projection and paths only) and the 110m world-atlas shapes,
 * which are fetched as a separate, cached file. Colors are a single-hue sequential ramp in
 * decade classes (1+, 10+, 100+, …), since trial counts span five orders of magnitude.
 * Places too small for the 110m shapes (Hong Kong, Singapore, Malta, …) are dots.
 * Clicking a country opens the trial list filtered to it.
 */
import { useNavigate } from "@tanstack/react-router";
import { geoNaturalEarth1, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { use, useMemo, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import worldUrl from "world-atlas/countries-110m.json?url";
import { countryName, flag, formatNumber } from "@/lib/format";
import { useWidth } from "@/lib/use-width";
import { cn } from "@/lib/utils";
import type { WidgetProps } from "./common";
import { NAME_TO_ALPHA2, NUMERIC_TO_ALPHA2 } from "./iso-numeric";

type Country = Feature<Geometry, { name: string }> & { code: string | undefined };

let world: Promise<Country[]> | undefined;

function loadWorld(): Promise<Country[]> {
  world ??= fetch(worldUrl)
    .then((response) => {
      if (!response.ok) throw new Error(`world map: ${response.status}`);
      return response.json() as Promise<
        Topology<{ countries: GeometryCollection<{ name: string }> }>
      >;
    })
    .then((topology) => {
      const collection = feature(topology, topology.objects.countries) as FeatureCollection<
        Geometry,
        { name: string }
      >;
      return collection.features
        .filter((shape) => shape.id !== "010") // Antarctica: space, and no trials
        .map((shape) => ({
          ...shape,
          code: NUMERIC_TO_ALPHA2[String(shape.id)] ?? NAME_TO_ALPHA2[shape.properties.name],
        }));
    })
    .catch((error: unknown) => {
      world = undefined; // let a later render try again
      throw error;
    });
  return world;
}

/** [longitude, latitude] of places the 110m shapes leave out. */
const SMALL_PLACES: Record<string, [number, number]> = {
  HK: [114.17, 22.32],
  SG: [103.82, 1.35],
  MO: [113.54, 22.19],
  MQ: [-61.02, 14.64],
  GP: [-61.55, 16.25],
  RE: [55.54, -21.12],
  MU: [57.55, -20.35],
  YT: [45.17, -12.83],
  MC: [7.42, 43.74],
  MT: [14.38, 35.94],
  BH: [50.56, 26.07],
  GU: [144.79, 13.44],
  AG: [-61.8, 17.06],
  BB: [-59.54, 13.19],
  LI: [9.55, 47.17],
  AD: [1.52, 42.51],
  SM: [12.46, 43.94],
  VA: [12.45, 41.9],
  GD: [-61.68, 12.12],
  LC: [-60.98, 13.91],
  KN: [-62.78, 17.36],
  DM: [-61.37, 15.41],
  VC: [-61.2, 13.25],
  BM: [-64.75, 32.31],
  KY: [-81.25, 19.31],
  VI: [-64.9, 18.34],
  AS: [-170.7, -14.27],
  PF: [-149.41, -17.65],
  WS: [-172.1, -13.76],
  FO: [-6.91, 61.89],
  JE: [-2.13, 49.21],
  KM: [43.87, -11.88],
  MP: [145.67, 15.1],
  NU: [-169.87, -19.05],
};

const MAX_HEIGHT = 430;
const LIST_WIDTH = 248;
const LEADERS = 10;

const CLASSES = ["1+", "10+", "100+", "1K+", "10K+", "100K+", "1M+"];
const STEPS = [100, 200, 300, 400, 500, 600, 700];

/** The decade class of a count: 0 for none, 1 for 1–9, 2 for 10–99, … */
export function decade(count: number): number {
  if (!(count >= 1)) return 0;
  return Math.min(CLASSES.length, Math.floor(Math.log10(count)) + 1);
}

/** The ramp step for class `level` of `levels`, spread over the whole ramp so that a few
 * classes (a narrow filter) still differ clearly. */
export function step(level: number, levels: number): number {
  const last = STEPS.length - 1;
  const index = levels <= 1 ? last : Math.round(((level - 1) * last) / (levels - 1));
  return STEPS[Math.min(last, Math.max(0, index))] ?? 700;
}

function fill(count: number, levels: number): string {
  const level = decade(count);
  return level === 0 ? "var(--seq-0)" : `var(--seq-${step(level, levels)})`;
}

type Hover = { code: string; x: number; y: number };

export default function MapWidget({ spec, rows, height }: WidgetProps) {
  const countries = use(loadWorld());
  const navigate = useNavigate();
  const [ref, width] = useWidth<HTMLDivElement>(900);
  const [hover, setHover] = useState<Hover | null>(null);

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) {
      const code = row[spec.x];
      if (typeof code === "string") map.set(code.toUpperCase(), Number(row[spec.y] ?? 0));
    }
    return map;
  }, [rows, spec.x, spec.y]);
  const labels = useMemo(
    () => new Map(rows.map((row) => [String(row[spec.x]).toUpperCase(), String(row.label ?? "")])),
    [rows, spec.x],
  );

  // Wide cards get a list of the leading countries beside the map.
  const list = width >= 900;
  const mapWidth = list ? width - LIST_WIDTH - 24 : width;
  const mapHeight = Math.max(150, Math.min(height, MAX_HEIGHT, mapWidth * 0.5));
  const { paths, dots, centers } = useMemo(() => {
    const projection = geoNaturalEarth1().fitExtent(
      [
        [4, 4],
        [Math.max(mapWidth - 4, 10), mapHeight - 4],
      ],
      { type: "FeatureCollection", features: countries },
    );
    const path = geoPath(projection);
    const centers = new Map<string, [number, number]>();
    const paths = countries.map((country) => {
      if (country.code && !centers.has(country.code))
        centers.set(country.code, path.centroid(country));
      return { country, d: path(country) ?? "" };
    });
    const dots = Object.entries(SMALL_PLACES)
      .filter(([code]) => (counts.get(code) ?? 0) > 0)
      .map(([code, at]) => ({ code, point: projection(at) }))
      .filter((dot): dot is { code: string; point: [number, number] } => dot.point !== null);
    for (const dot of dots) centers.set(dot.code, dot.point);
    return { paths, dots, centers };
  }, [countries, counts, mapWidth, mapHeight]);

  const leaders = useMemo(
    () => [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, LEADERS),
    [counts],
  );
  const max = Math.max(0, ...counts.values());
  const levels = Math.max(1, decade(max));
  const hovered = hover ? counts.get(hover.code) : undefined;
  const open = (code: string) => {
    if (counts.get(code)) void navigate({ to: "/trials", search: { countries: [code] } });
  };

  const track = (code: string | undefined) => (event: React.PointerEvent) => {
    if (!code) return setHover(null);
    const box = event.currentTarget.closest("svg")?.getBoundingClientRect();
    if (box) setHover({ code, x: event.clientX - box.left, y: event.clientY - box.top });
  };

  const point = (code: string) => {
    const center = centers.get(code);
    if (center) setHover({ code, x: center[0], y: center[1] });
  };

  return (
    <div ref={ref} className="flex w-full flex-col gap-3">
      <div className="flex items-center gap-6">
        <div className="relative min-w-0 flex-1">
          <svg
            width={mapWidth}
            height={mapHeight}
            viewBox={`0 0 ${mapWidth} ${mapHeight}`}
            role="img"
            aria-label={`${spec.title}: ${counts.size} countries; the table view lists them all.`}
            className="mx-auto block max-w-full"
            onPointerLeave={() => setHover(null)}
          >
            <g>
              {paths.map(({ country, d }) => {
                const code = country.code;
                const count = code ? (counts.get(code) ?? 0) : 0;
                return (
                  // biome-ignore lint/a11y/noStaticElementInteractions: the table view is the keyboard path
                  <path
                    key={`${country.id ?? country.properties.name}`}
                    d={d}
                    fill={fill(count, levels)}
                    stroke="var(--card)"
                    strokeWidth={0.6}
                    className={cn(count > 0 && "cursor-pointer")}
                    style={
                      hover?.code === code
                        ? { stroke: "var(--foreground)", strokeWidth: 1 }
                        : undefined
                    }
                    onPointerMove={track(code)}
                    onClick={() => code && open(code)}
                  />
                );
              })}
            </g>
            <g>
              {dots.map(({ code, point: [x, y] }) => (
                // biome-ignore lint/a11y/noStaticElementInteractions: the table view is the keyboard path
                <g
                  key={code}
                  onPointerMove={track(code)}
                  onClick={() => open(code)}
                  className="cursor-pointer"
                >
                  <circle cx={x} cy={y} r={9} fill="transparent" />
                  <circle
                    cx={x}
                    cy={y}
                    r={hover?.code === code ? 4.5 : 3.5}
                    fill={fill(counts.get(code) ?? 0, levels)}
                    stroke="var(--card)"
                    strokeWidth={1.5}
                  />
                </g>
              ))}
            </g>
          </svg>
          {hover && (
            <div
              className="pointer-events-none absolute z-10 grid min-w-32 gap-0.5 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg"
              style={{
                left: Math.min(hover.x + 14, mapWidth - 180),
                top: Math.max(hover.y - 52, 0),
              }}
            >
              <span className="text-sm font-semibold tabular text-popover-foreground">
                {hovered ? `${formatNumber(hovered)} trials` : "No trials"}
              </span>
              <span className="text-muted-foreground">
                {flag(hover.code)} {labels.get(hover.code) || countryName(hover.code)}
              </span>
            </div>
          )}
        </div>
        {list && (
          <ol
            className="grid shrink-0 gap-0.5 text-sm"
            style={{ width: LIST_WIDTH }}
            aria-label="Leading countries"
          >
            {leaders.map(([code, count], index) => (
              <li key={code}>
                <button
                  type="button"
                  className={cn(
                    "group grid w-full grid-cols-[1.25rem_1fr_auto] items-center gap-x-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-muted",
                    hover?.code === code && "bg-muted",
                  )}
                  onPointerEnter={() => point(code)}
                  onPointerLeave={() => setHover(null)}
                  onFocus={() => point(code)}
                  onBlur={() => setHover(null)}
                  onClick={() => open(code)}
                >
                  <span className="text-xs tabular text-muted-foreground">{index + 1}</span>
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span aria-hidden="true">{flag(code)}</span>
                    <span className="truncate">{labels.get(code) || countryName(code)}</span>
                  </span>
                  <span className="text-xs font-medium tabular">{formatNumber(count)}</span>
                  <span className="col-start-2 col-end-4 mt-1 h-1 overflow-hidden rounded-full bg-muted group-hover:bg-background">
                    <span
                      className="block h-full rounded-full"
                      style={{
                        width: `${(count / (leaders[0]?.[1] || 1)) * 100}%`,
                        background: "var(--seq-500)",
                      }}
                    />
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
        <span>Trials per country</span>
        <span className="flex items-center gap-1.5">
          <span
            className="size-2.5 rounded-[3px] border border-border"
            style={{ background: "var(--seq-0)" }}
          />
          None
        </span>
        {CLASSES.slice(0, levels).map((label, index) => (
          <span key={label} className="flex items-center gap-1.5">
            <span
              className="size-2.5 rounded-[3px]"
              style={{ background: `var(--seq-${step(index + 1, levels)})` }}
            />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
