import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { ArrowUpRight, Copy, MapPin, UserRound, Users } from "lucide-react";
import { useEffect } from "react";
import type { Change, TrialDetail } from "@/api/client";
import { changesQuery, trialQuery } from "@/api/queries";
import { ErrorState } from "@/components/route-states";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatNumber, humanize } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { notify } from "@/lib/notify";
import type { TrialTab } from "@/router";
import { ChangesTab } from "./changes";
import { LocationsTab } from "./locations";
import { EligibilityTab, OutcomesTab, OverviewTab } from "./sections";
import { TrialTimeline } from "./timeline";

const route = getRouteApi("/trials/$sourceId");

const REGISTRY_URL: Record<string, (id: string) => string> = {
  ctgov: (id) => `https://clinicaltrials.gov/study/${encodeURIComponent(id)}`,
};

export function TrialPage() {
  const { sourceId } = route.useParams();
  const { tab = "overview" } = route.useSearch();
  const navigate = route.useNavigate();
  const trial = useQuery(trialQuery(sourceId));
  const changes = useQuery(changesQuery(sourceId));
  // The API finds an ID in small letters too (/trials/nct04437511); show the trial's own.
  const canonical = trial.data?.source_id;
  useEffect(() => {
    if (canonical && canonical !== sourceId) {
      void navigate({
        to: "/trials/$sourceId",
        params: { sourceId: canonical },
        search: (prev) => prev,
        replace: true,
      });
    }
  }, [canonical, sourceId, navigate]);

  if (trial.isError) {
    return <ErrorState error={trial.error} onRetry={() => void trial.refetch()} />;
  }
  const data = trial.data;

  return (
    <main
      className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 p-4 sm:p-6"
      data-testid="trial"
    >
      {data ? <Header trial={data} changes={changes.data?.changes} /> : <HeaderSkeleton />}
      <Tabs
        value={tab}
        onValueChange={(value) =>
          void navigate({
            search: value === "overview" ? {} : { tab: value as TrialTab },
            replace: true,
            resetScroll: false,
          })
        }
        className="gap-4"
      >
        <div className="no-scrollbar -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <TabsList className="w-max">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="eligibility">Eligibility</TabsTrigger>
            <TabsTrigger value="outcomes">
              Outcomes <Count value={data?.outcomes.length} />
            </TabsTrigger>
            <TabsTrigger value="locations">
              Locations <Count value={data?.locations.length} />
            </TabsTrigger>
            <TabsTrigger value="changes">
              Changes <Count value={changes.data?.changes.length} />
            </TabsTrigger>
          </TabsList>
        </div>
        {data ? (
          <>
            <TabsContent value="overview">
              <OverviewTab trial={data} />
            </TabsContent>
            <TabsContent value="eligibility">
              <EligibilityTab trial={data} />
            </TabsContent>
            <TabsContent value="outcomes">
              <OutcomesTab trial={data} />
            </TabsContent>
            <TabsContent value="locations">
              <LocationsTab trial={data} />
            </TabsContent>
            <TabsContent value="changes">
              <ChangesTab query={changes} />
            </TabsContent>
          </>
        ) : (
          <Skeleton className="h-80 w-full rounded-xl" />
        )}
      </Tabs>
    </main>
  );
}

function Count({ value }: { value: number | undefined }) {
  if (!value) return null;
  return (
    <span className="rounded-full bg-muted px-1.5 text-[0.65rem] leading-4 font-medium text-muted-foreground tabular group-data-[state=active]:bg-foreground/10 group-data-[state=active]:text-foreground">
      {formatNumber(value)}
    </span>
  );
}

function Header({ trial, changes }: { trial: TrialDetail; changes?: Change[] }) {
  const label = useLabels();
  const url = REGISTRY_URL[trial.source]?.(trial.source_id);
  return (
    <header className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="group inline-flex h-6 items-center gap-1.5 rounded-md border bg-card px-2 font-mono text-xs font-medium transition-colors hover:bg-muted"
            title="Copy the id"
            onClick={() => {
              void navigator.clipboard?.writeText(trial.source_id);
              notify.message(`Copied ${trial.source_id}`);
            }}
          >
            {trial.source_id}
            <Copy className="size-3 text-muted-foreground group-hover:text-foreground" />
          </button>
          <StatusBadge status={trial.status} />
          {trial.status === "UNKNOWN" && trial.last_known_status && (
            <Badge
              variant="outline"
              className="h-6 rounded-full px-2 text-muted-foreground"
              title="ClinicalTrials.gov marks a trial Unknown when its status hasn't been verified in two years"
            >
              Last known: {label("status", trial.last_known_status)}
            </Badge>
          )}
          {trial.phase && (
            <Badge variant="outline" className="h-6 rounded-full px-2">
              {label("phase", trial.phase)}
            </Badge>
          )}
          {trial.study_type && (
            <Badge variant="outline" className="h-6 rounded-full px-2">
              {label("study_type", trial.study_type)}
            </Badge>
          )}
          {trial.has_results && (
            <Badge variant="outline" className="h-6 rounded-full border-good/30 bg-good/8 px-2">
              Has results
            </Badge>
          )}
        </div>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-1.5">
            <h1 className="text-xl font-semibold tracking-tight text-balance sm:text-2xl">
              {trial.title}
            </h1>
            {trial.official_title && trial.official_title !== trial.title && (
              <p className="max-w-3xl text-sm text-muted-foreground">{trial.official_title}</p>
            )}
          </div>
          <div className="flex shrink-0 gap-2">
            {url && (
              <Button asChild variant="outline" size="sm">
                <a href={url} target="_blank" rel="noreferrer">
                  ClinicalTrials.gov
                  <ArrowUpRight />
                </a>
              </Button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
          {trial.sponsors
            .filter((sponsor) => sponsor.role === "lead")
            .map((sponsor) => (
              <Link
                key={sponsor.name}
                to="/trials"
                search={{ sponsors: [sponsor.name] }}
                className="inline-flex items-center gap-1.5 hover:text-foreground"
              >
                <Users className="size-3.5" />
                {sponsor.name}
              </Link>
            ))}
          {trial.enrollment !== null && (
            <span className="inline-flex items-center gap-1.5">
              <UserRound className="size-3.5" />
              {formatNumber(trial.enrollment)} participants
              {trial.enrollment_type && ` (${humanize(trial.enrollment_type).toLowerCase()})`}
            </span>
          )}
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <MapPin className="size-3.5 shrink-0" />
            <span className="truncate">
              {trial.locations.length > 0
                ? `${formatNumber(trial.locations.length)} site${trial.locations.length === 1 ? "" : "s"} in ${formatNumber(trial.countries.length)} countr${trial.countries.length === 1 ? "y" : "ies"}`
                : "No sites listed"}
            </span>
          </span>
        </div>
      </div>
      <TrialTimeline trial={trial} changes={changes} />
    </header>
  );
}

function HeaderSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        <Skeleton className="h-6 w-28" />
        <Skeleton className="h-6 w-24 rounded-full" />
        <Skeleton className="h-6 w-20 rounded-full" />
      </div>
      <Skeleton className="h-8 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="mt-2 h-16 w-full rounded-xl" />
    </div>
  );
}
