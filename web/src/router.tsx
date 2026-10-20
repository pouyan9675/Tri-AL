/**
 * Routes. Each page is its own chunk, loaded when first visited; a route's loader starts its
 * data requests while the chunk downloads, so the two overlap.
 */
import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
} from "@tanstack/react-router";
import { advancedSearchQuery } from "@/api/advanced";
import {
  chartQuery,
  dashboardQuery,
  linkedTrialsQuery,
  metaQuery,
  onPage,
  trialQuery,
} from "@/api/queries";
import { termQuery } from "@/api/terms";
import { AppShell } from "@/components/app-shell";
import { NotFound, RouteError } from "@/components/route-states";
import { hasQuery, parseAdvancedSearch } from "@/lib/advanced";
import { parseFilter, parseTrialsSearch } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { parseLinkingSearch, parseTermSearch } from "@/pages/analysis/sections";

export type RouterContext = { queryClient: QueryClient };

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
  notFoundComponent: NotFound,
  errorComponent: RouteError,
});

export const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  staticData: { title: "Dashboard" },
  validateSearch: parseFilter,
  loaderDeps: ({ search }) => search,
  loader: async ({ context: { queryClient }, deps }) => {
    void queryClient.prefetchQuery(metaQuery());
    const dashboard = await queryClient.ensureQueryData(dashboardQuery()).catch(() => null);
    for (const chart of onPage(dashboard?.charts, "dashboard")) {
      void queryClient.prefetchQuery(chartQuery(chart.id, deps));
    }
  },
  component: lazyRouteComponent(() => import("@/pages/dashboard"), "DashboardPage"),
});

// The analysis page frames its sections (`pages/analysis/sections.ts`), one route each; they
// share its filter.
export const analysisRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analysis",
  staticData: { title: "Analysis" },
  validateSearch: parseFilter,
  component: lazyRouteComponent(() => import("@/pages/analysis"), "AnalysisPage"),
});

export const analysisLandscapeRoute = createRoute({
  getParentRoute: () => analysisRoute,
  path: "/",
  staticData: { title: "Landscape" },
  loaderDeps: ({ search }) => search,
  loader: async ({ context: { queryClient }, deps }) => {
    const dashboard = await queryClient.ensureQueryData(dashboardQuery()).catch(() => null);
    for (const chart of onPage(dashboard?.charts, "analysis")) {
      void queryClient.prefetchQuery(chartQuery(chart.id, deps));
    }
  },
  component: lazyRouteComponent(() => import("@/pages/analysis"), "LandscapeSection"),
});

export const analysisLinkingRoute = createRoute({
  getParentRoute: () => analysisRoute,
  path: "linking",
  staticData: { title: "Trial linking" },
  validateSearch: parseLinkingSearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context: { queryClient }, deps: { trial, terms, ...filter } }) => {
    if (trial) void queryClient.prefetchQuery(linkedTrialsQuery(trial, terms, filter));
  },
  component: lazyRouteComponent(() => import("@/pages/analysis/linking"), "LinkingSection"),
});

// Advanced search (`pages/analysis/search`): its fields sit beside the filter in the URL.
export const analysisSearchRoute = createRoute({
  getParentRoute: () => analysisRoute,
  path: "search",
  staticData: { title: "Advanced search" },
  validateSearch: parseAdvancedSearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context: { queryClient }, deps }) => {
    const search = parseAdvancedSearch(deps);
    if (hasQuery(search)) {
      void queryClient.prefetchInfiniteQuery(advancedSearchQuery(search, parseFilter(deps)));
    }
  },
  component: lazyRouteComponent(() => import("@/pages/analysis/search"), "AdvancedSearchSection"),
});

// A MeSH term in depth (`pages/analysis/terms`); its first request starts with the chunk.
export const analysisConditionsRoute = createRoute({
  getParentRoute: () => analysisRoute,
  path: "conditions",
  staticData: { title: "Conditions" },
  validateSearch: parseTermSearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context: { queryClient }, deps: { term, ...filter } }) => {
    if (term) void queryClient.prefetchQuery(termQuery("condition", term, filter));
  },
  component: lazyRouteComponent(() => import("@/pages/analysis/terms"), "ConditionsSection"),
});

export const analysisInterventionsRoute = createRoute({
  getParentRoute: () => analysisRoute,
  path: "interventions",
  staticData: { title: "Interventions" },
  validateSearch: parseTermSearch,
  loaderDeps: ({ search }) => search,
  loader: ({ context: { queryClient }, deps: { term, ...filter } }) => {
    if (term) void queryClient.prefetchQuery(termQuery("intervention", term, filter));
  },
  component: lazyRouteComponent(() => import("@/pages/analysis/terms"), "InterventionsSection"),
});

export const trialsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/trials",
  staticData: { title: "Trials" },
  validateSearch: parseTrialsSearch,
  component: lazyRouteComponent(() => import("@/pages/trials"), "TrialsPage"),
});

export const TRIAL_TABS = [
  "overview",
  "eligibility",
  "outcomes",
  "results",
  "locations",
  "changes",
] as const;
export type TrialTab = (typeof TRIAL_TABS)[number];

export const trialRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/trials/$sourceId",
  staticData: { title: "Trial" },
  validateSearch: (search: Record<string, unknown>): { tab?: TrialTab } => {
    const tab = TRIAL_TABS.find((name) => name === search.tab);
    return tab && tab !== "overview" ? { tab } : {};
  },
  loader: ({ context: { queryClient }, params }) => {
    void queryClient.prefetchQuery(trialQuery(params.sourceId));
  },
  component: lazyRouteComponent(() => import("@/pages/trial"), "TrialPage"),
});

export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  staticData: { title: "Settings" },
  component: lazyRouteComponent(() => import("@/pages/settings"), "SettingsPage"),
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  analysisRoute.addChildren([
    analysisLandscapeRoute,
    analysisLinkingRoute,
    analysisSearchRoute,
    analysisConditionsRoute,
    analysisInterventionsRoute,
  ]),
  trialsRoute,
  trialRoute,
  settingsRoute,
]);

export function makeRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    parseSearch,
    stringifySearch,
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0, // TanStack Query decides what's fresh
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
  interface StaticDataRouteOption {
    title?: string;
  }
}
