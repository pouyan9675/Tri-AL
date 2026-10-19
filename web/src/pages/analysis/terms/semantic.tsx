/**
 * What its trials are about, from their text vectors. Sub-themes (#9): its trials clustered,
 * on a map that spreads the clusters apart, each named by its distinctive title words, with
 * its distinctive MeSH terms, its growth and examples; choosing one picks it out on the map.
 * Similar terms (#10): the terms whose trials read most alike, across the registry, marked
 * when they're never tagged on the same trial.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import type { SimilarTerm, TermKind, TermThemes, Theme } from "@/api/client";
import { termSimilarQuery, termThemesQuery } from "@/api/terms";
import { Badge } from "@/components/ui/badge";
import type { TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { buildDots, LandscapePlot, type LandscapePoint } from "@/widgets/scatter";
import { Meter } from "@/widgets/trends";
import { AnalysisCard, KINDS, otherKind, percent, TermLink, times } from "./common";

export function ThemesCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termThemesQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="Sub-themes"
      description="Its trials grouped by what their text is about, each named by the words that set it apart. Growth compares trials started in the last 3 years with earlier ones."
      query={query}
      testId="term-themes"
      height={380}
      wide
    >
      {(data) => <Themes data={data} />}
    </AnalysisCard>
  );
}

const themeColor = (cluster: number) => `var(--chart-${(cluster % 8) + 1})`;

function Themes({ data }: { data: TermThemes }) {
  const [chosen, setChosen] = useState<number | null>(null);
  const byCluster = useMemo(
    () => new Map(data.themes.map((theme) => [theme.cluster, theme])),
    [data.themes],
  );
  const drawn = useMemo(() => {
    const points: LandscapePoint[] = data.points.map((point) => {
      const theme = byCluster.get(point.cluster);
      return {
        x: point.x,
        y: -point.y,
        cluster: point.cluster,
        cluster_label: theme?.label ?? "",
        cluster_size: theme?.size ?? 0,
        color: chosen === null || chosen === point.cluster ? point.cluster % 8 : null,
        title: point.title,
        source_id: point.source_id,
      };
    });
    return buildDots(points);
  }, [data.points, byCluster, chosen]);

  if (data.embedded === 0) {
    return (
      <Unavailable
        title="Embed the trials to find sub-themes"
        detail="Sub-themes come from the trials' text vectors. Run `tri-al embeddings generate` (about five minutes for every trial); each update embeds its new and changed trials."
      />
    );
  }
  if (data.themes.length === 0) {
    return (
      <Unavailable
        title="Too few trials for sub-themes"
        detail={`Sub-themes need 30 trials with vectors; ${formatNumber(data.embedded)} of its trials have one within the filter.`}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="font-medium text-foreground tabular">{formatNumber(data.sampled)}</span>{" "}
          trials grouped
          {data.sampled < data.embedded ? ` (spread over ${formatNumber(data.embedded)})` : ""}
        </span>
        <span>{data.themes.length} sub-themes</span>
        {data.silhouette !== null && (
          <span title="How well the groups separate, from -1 to 1. Trial texts overlap, so around 0.1 is usual.">
            Separation {data.silhouette.toFixed(2)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <LandscapePlot drawn={drawn} height={380} />
        <ol className="flex max-h-[380px] flex-col gap-1 overflow-y-auto" aria-label="Sub-themes">
          {data.themes.map((theme) => (
            <ThemeItem
              key={theme.cluster}
              theme={theme}
              chosen={chosen === theme.cluster}
              faded={chosen !== null && chosen !== theme.cluster}
              onChoose={() => setChosen(chosen === theme.cluster ? null : theme.cluster)}
            />
          ))}
        </ol>
      </div>
    </div>
  );
}

function ThemeItem({
  theme,
  chosen,
  faded,
  onChoose,
}: {
  theme: Theme;
  chosen: boolean;
  faded: boolean;
  onChoose: () => void;
}) {
  const Icon = theme.confidence === "low" ? Minus : theme.growth >= 1 ? TrendingUp : TrendingDown;
  return (
    <li
      className={cn(
        "flex flex-col gap-1 rounded-lg border px-3 py-2 transition-opacity",
        chosen && "border-foreground/30 bg-muted/40",
        faded && "opacity-50",
      )}
    >
      <button
        type="button"
        aria-pressed={chosen}
        onClick={onChoose}
        className="flex items-center gap-2 text-left focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <span
          className="size-2.5 shrink-0 rounded-full"
          style={{ background: themeColor(theme.cluster) }}
        />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{theme.label}</span>
        <span className="text-xs text-muted-foreground tabular">
          {formatNumber(theme.size)} · {percent(theme.share)}
        </span>
      </button>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-4.5 text-xs text-muted-foreground">
        <span
          className="flex items-center gap-1"
          title="Its share of trials started in the last 3 years, over its share of earlier ones."
        >
          <Icon className="size-3.5" />
          <span className="tabular">{times(theme.growth)}</span> recent share
          <Meter confidence={theme.confidence} />
        </span>
        {theme.terms.map((term) => (
          <TermLink key={`${term.kind}-${term.code}`} kind={term.kind} code={term.code}>
            {term.term}
          </TermLink>
        ))}
      </div>
      {chosen && (
        <ul className="mt-1 flex flex-col gap-1 pl-4.5">
          {theme.examples.map((example) => (
            <li key={example.source_id} className="text-xs">
              <Link
                to="/trials/$sourceId"
                params={{ sourceId: example.source_id }}
                className="decoration-muted-foreground/40 underline-offset-2 hover:underline"
              >
                {example.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function Unavailable({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed px-6 text-center">
      <div className="font-medium">{title}</div>
      <div className="mt-2 max-w-lg text-sm text-muted-foreground">{detail}</div>
    </div>
  );
}

export function SimilarCard({ kind, code }: { kind: TermKind; code: string }) {
  const query = useQuery(termSimilarQuery(kind, code));
  return (
    <AnalysisCard
      title="Similar terms"
      description="Terms whose trials read most like its trials (their average text vectors), across the whole registry: the filter doesn't apply. Those never tagged on the same trial point to adjacent research."
      query={query}
      testId="term-similar"
      height={300}
      wide
    >
      {(data) =>
        data.embedded === 0 ? (
          <Unavailable
            title="Embed the trials to find similar terms"
            detail="Run `tri-al embeddings generate`; similar terms come from the trials' text vectors."
          />
        ) : (
          <div className="grid grid-cols-1 gap-6 @3xl:grid-cols-2">
            <SimilarList title={`Similar ${KINDS[kind].many}`} terms={data.same} />
            <SimilarList
              title={`${KINDS[otherKind(kind)].Many} whose trials read alike`}
              terms={data.other}
            />
          </div>
        )
      }
    </AnalysisCard>
  );
}

function SimilarList({ title, terms }: { title: string; terms: SimilarTerm[] }) {
  const lowest = Math.min(...terms.map((term) => term.similarity), 0.5);
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="similar-list">
      <div className="text-xs font-medium">{title}</div>
      {terms.length === 0 ? (
        <p className="py-4 text-xs text-muted-foreground">None with enough trials.</p>
      ) : (
        <ol className="divide-y">
          {terms.map((term) => (
            <li
              key={term.code}
              className="grid grid-cols-[minmax(0,1fr)_5rem_auto] items-center gap-x-3 py-1.5 text-xs"
            >
              <span className="flex min-w-0 items-center gap-2">
                <TermLink kind={term.kind} code={term.code} className="truncate font-medium">
                  <span title={term.term}>{term.term}</span>
                </TermLink>
                {term.shared === 0 && (
                  <Badge
                    variant="secondary"
                    className="h-4.5 shrink-0 px-1.5 text-[0.65rem] font-normal"
                    title="No trial is tagged with both"
                  >
                    Never together
                  </Badge>
                )}
              </span>
              <span
                className="flex items-center gap-1.5"
                title={`Cosine similarity ${term.similarity.toFixed(3)}`}
              >
                <span className="h-1.5 flex-1 rounded-full bg-muted">
                  <span
                    className="block h-full rounded-full bg-chart-1"
                    style={{
                      width: `${Math.max(4, ((term.similarity - lowest) / (1 - lowest)) * 100)}%`,
                    }}
                  />
                </span>
                <span className="w-7 text-right tabular">{term.similarity.toFixed(2)}</span>
              </span>
              <span className="text-right text-muted-foreground tabular">
                {term.shared > 0
                  ? `${formatNumber(term.shared)} of ${formatNumber(term.trials)} shared`
                  : `${formatNumber(term.trials)} trials`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
