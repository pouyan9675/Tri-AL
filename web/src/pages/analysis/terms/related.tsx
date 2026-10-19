/**
 * Related terms (#3) and their network (#4), from one request. Related terms are tagged on
 * the term's trials more often than on the filter's other trials, ranked by confidence, then
 * lift. The network draws the term in the middle and its most related terms around it,
 * joined when they share trials, coloured by the groups modularity finds among them.
 */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import type { NetworkNode, RelatedTerm, TermKind, TermRelated } from "@/api/client";
import { termRelatedQuery } from "@/api/terms";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { parseFilter, type TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useWidth } from "@/lib/use-width";
import { cn } from "@/lib/utils";
import { fitText, textWidth } from "@/widgets/common";
import { formatChance, Meter } from "@/widgets/trends";
import { AnalysisCard, analysis, KINDS, percent, TermLink, times } from "./common";
import { layoutNetwork, placeLabels } from "./network-layout";

type Props = { kind: TermKind; code: string; filter: TrialFilter };

export function RelatedCard({ kind, code, filter }: Props) {
  const query = useQuery(termRelatedQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="Related conditions and interventions"
      description="Tagged on its trials more often than on the filter's other trials. Lift is how many times more often, smoothed for small counts; confidence is corrected for every term tested."
      query={query}
      testId="term-related"
      wide
    >
      {(data) =>
        data.conditions.length + data.interventions.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No term is tagged on 3 or more of its trials more often than elsewhere.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-6 @3xl:grid-cols-2">
            <RelatedList title="Conditions" terms={data.conditions} tested={data.tested} />
            <RelatedList title="Interventions" terms={data.interventions} tested={data.tested} />
          </div>
        )
      }
    </AnalysisCard>
  );
}

const COLUMNS = "grid grid-cols-[minmax(0,1fr)_3.5rem_4rem_3.5rem] items-center gap-x-3";

function RelatedList({
  title,
  terms,
  tested,
}: {
  title: string;
  terms: RelatedTerm[];
  tested: number;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid={`related-${title.toLowerCase()}`}>
      <div className={cn(COLUMNS, "text-[0.7rem] text-muted-foreground")}>
        <span className="font-medium text-foreground">{title}</span>
        <span className="text-right">Trials</span>
        <span className="text-right">Lift</span>
        <span className="text-right">Sure</span>
      </div>
      {terms.length === 0 ? (
        <p className="py-4 text-xs text-muted-foreground">None stand out.</p>
      ) : (
        <ol className="divide-y">
          {terms.map((term) => (
            <li
              key={term.code}
              className={cn(COLUMNS, "py-1.5 text-xs", term.confidence === "low" && "opacity-60")}
            >
              <TermLink kind={term.kind} code={term.code} className="truncate font-medium">
                <span title={term.term}>{term.term}</span>
              </TermLink>
              <span className="text-right tabular">{formatNumber(term.trials)}</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-default text-right font-semibold tabular">
                    {times(term.lift)}
                  </span>
                </TooltipTrigger>
                <TooltipContent className="max-w-72 text-xs">
                  On {percent(term.share, 1)} of its trials against {percent(term.elsewhere, 2)} of
                  the filter's others. p = {formatChance(term.p)}; corrected for the{" "}
                  {formatNumber(tested)} terms tested, q = {formatChance(term.q)}.
                </TooltipContent>
              </Tooltip>
              <Meter confidence={term.confidence} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function NetworkCard({ kind, code, filter }: Props) {
  const query = useQuery(termRelatedQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="Network"
      description="Its most related terms, joined when they're tagged on the same trials (thicker: more alike). Colours are groups that go together."
      query={query}
      testId="term-network"
      height={360}
    >
      {(data) =>
        data.nodes.length <= 1 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No related terms to draw.
          </p>
        ) : (
          <Network data={data} />
        )
      }
    </AnalysisCard>
  );
}

const HEIGHT = 380;
/** Room for labels at the sides, and for half a node above and below. */
const PAD_X = 100;
const PAD_Y = 22;

const nodeColor = (node: NetworkNode) =>
  node.center ? "var(--foreground)" : `var(--chart-${(node.group % 8) + 1})`;

function Network({ data }: { data: TermRelated }) {
  const navigate = useNavigate();
  const filter = parseFilter(analysis.useSearch());
  const [ref, width] = useWidth<HTMLDivElement>(480);
  const [hovered, setHovered] = useState<number | null>(null);
  const positions = useMemo(() => layoutNetwork(data.nodes, data.edges), [data]);
  const largest = Math.max(1, ...data.nodes.filter((n) => !n.center).map((n) => n.trials));
  const strongest = Math.max(1e-9, ...data.edges.map((edge) => edge.jaccard));
  const x = (i: number) =>
    PAD_X + (((positions[i]?.x ?? 0) + 1) / 2) * Math.max(0, width - 2 * PAD_X);
  const y = (i: number) => PAD_Y + (((positions[i]?.y ?? 0) + 1) / 2) * (HEIGHT - 2 * PAD_Y);
  const radius = (node: NetworkNode) =>
    node.center ? 9 : 3.5 + 7 * Math.sqrt(node.trials / largest);
  const near = new Set<number>();
  if (hovered !== null) {
    near.add(hovered);
    for (const edge of data.edges) {
      if (edge.source === hovered) near.add(edge.target);
      if (edge.target === hovered) near.add(edge.source);
    }
  }
  const lit = (i: number) => hovered === null || near.has(i) || i === 0;
  const names = data.nodes.map((item) =>
    fitText(item.term, item.center ? 160 : 110, item.center ? 12 : 10.5),
  );
  const sides = placeLabels(
    data.nodes.map((item, i) => ({
      x: x(i),
      y: y(i),
      r: radius(item),
      width: textWidth(names[i] ?? "", item.center ? 12 : 10.5),
      height: item.center ? 15 : 13,
      priority: item.center ? Number.POSITIVE_INFINITY : item.trials,
      prefer: (positions[i]?.x ?? 0) <= 0 ? "left" : "right",
    })),
  );
  const node = hovered === null ? undefined : data.nodes[hovered];

  return (
    <div ref={ref} className="relative flex flex-col gap-2">
      <svg
        width={width}
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-label={`${data.nodes[0]?.term} and its most related terms`}
        className="overflow-visible"
      >
        <g>
          {data.nodes.map((_, i) =>
            i === 0 ? null : (
              <line
                // biome-ignore lint/suspicious/noArrayIndexKey: one spoke per node, in order
                key={`spoke-${i}`}
                x1={x(0)}
                y1={y(0)}
                x2={x(i)}
                y2={y(i)}
                className="stroke-muted-foreground"
                strokeOpacity={hovered === i ? 0.4 : 0.08}
                strokeWidth={1}
              />
            ),
          )}
          {data.edges.map((edge) => (
            <line
              key={`${edge.source}-${edge.target}`}
              x1={x(edge.source)}
              y1={y(edge.source)}
              x2={x(edge.target)}
              y2={y(edge.target)}
              className="stroke-muted-foreground"
              strokeOpacity={
                hovered === null
                  ? 0.35
                  : edge.source === hovered || edge.target === hovered
                    ? 0.8
                    : 0.06
              }
              strokeWidth={1 + 3 * (edge.jaccard / strongest)}
            />
          ))}
        </g>
        {data.nodes.map((item, i) => {
          const r = radius(item);
          const shape =
            item.kind === "condition" ? (
              <circle cx={x(i)} cy={y(i)} r={r} />
            ) : (
              <rect x={x(i) - r} y={y(i) - r} width={2 * r} height={2 * r} rx={2} />
            );
          const side = sides[i] ?? (hovered === i ? "right" : null);
          return (
            // biome-ignore lint/a11y/useSemanticElements: an SVG node can't be a button
            <g
              key={`${item.kind}-${item.code}`}
              role="button"
              tabIndex={0}
              aria-label={`${item.term}, ${KINDS[item.kind].one}`}
              className="cursor-pointer outline-none"
              style={{ opacity: lit(i) ? 1 : 0.2, transition: "opacity 120ms" }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(i)}
              onBlur={() => setHovered(null)}
              onClick={() =>
                !item.center &&
                void navigate({
                  to: KINDS[item.kind].to,
                  search: { ...filter, term: item.code },
                })
              }
              onKeyDown={(event) => {
                if (event.key === "Enter" && !item.center) {
                  void navigate({
                    to: KINDS[item.kind].to,
                    search: { ...filter, term: item.code },
                  });
                }
              }}
            >
              <g fill={nodeColor(item)} stroke="var(--card)" strokeWidth={2}>
                {shape}
              </g>
              {side && (
                <text
                  x={x(i) + (side === "right" ? r + 4 : -r - 4)}
                  y={y(i)}
                  dy={3.5}
                  textAnchor={side === "right" ? "start" : "end"}
                  fontSize={item.center ? 12 : 10.5}
                  fontWeight={item.center ? 600 : 400}
                  className="fill-foreground"
                  stroke="var(--card)"
                  strokeWidth={3}
                  paintOrder="stroke"
                >
                  {names[i]}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {node && !node.center && (
        <div
          className="pointer-events-none absolute z-10 w-max max-w-64 rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md"
          style={{
            left: Math.min(width - 200, Math.max(0, x(hovered ?? 0) + 12)),
            top: Math.max(0, y(hovered ?? 0) - 12),
          }}
          role="tooltip"
        >
          <div className="font-medium">{node.term}</div>
          <div className="mt-1 text-muted-foreground">
            A related {KINDS[node.kind].one}: on {formatNumber(node.trials)} of its trials,{" "}
            {times(node.lift)} as often as elsewhere. Click to analyse it.
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden="true">
            <circle cx="5" cy="5" r="4.5" className="fill-muted-foreground" />
          </svg>
          Condition
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="10" aria-hidden="true">
            <rect x="0.5" y="0.5" width="9" height="9" rx="2" className="fill-muted-foreground" />
          </svg>
          Intervention
        </span>
        <span>Size: trials shared with {data.nodes[0]?.term}</span>
      </div>
    </div>
  );
}
