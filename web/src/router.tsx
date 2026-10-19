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
import { chartQuery, dashboardQuery, metaQuery, onPage, trialQuery } from "@/api/queries";
import { AppShell } from "@/components/app-shell";
import { NotFound, RouteError } from "@/components/route-states";
import { parseFilter, parseTrialsSearch } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";

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

export const analysisRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analysis",
  staticData: { title: "Analysis" },
  validateSearch: parseFilter,
  loaderDeps: ({ search }) => search,
  loader: async ({ context: { queryClient }, deps }) => {
    const dashboard = await queryClient.ensureQueryData(dashboardQuery()).catch(() => null);
    for (const chart of onPage(dashboard?.charts, "analysis")) {
      void queryClient.prefetchQuery(chartQuery(chart.id, deps));
    }
  },
  component: lazyRouteComponent(() => import("@/pages/analysis"), "AnalysisPage"),
});

export const trialsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/trials",
  staticData: { title: "Trials" },
  validateSearch: parseTrialsSearch,
  component: lazyRouteComponent(() => import("@/pages/trials"), "TrialsPage"),
});

export const TRIAL_TABS = ["overview", "eligibility", "outcomes", "locations", "changes"] as const;
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
  analysisRoute,
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
