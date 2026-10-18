import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";
import type { Job } from "@/api/client";
import { formatNumber } from "./format";
import { type LiveCallbacks, LiveEvents, type LiveState } from "./live";
import { notify } from "./notify";

const LiveContext = createContext<LiveEvents | null>(null);

type RunSummary = { sources?: Record<string, { new?: number; updated?: number }> };

function summarize(job: Job): string | undefined {
  const sources = Object.values((job.result as RunSummary | null)?.sources ?? {});
  if (!sources.length) return undefined;
  const added = sources.reduce((sum, source) => sum + (source.new ?? 0), 0);
  const updated = sources.reduce((sum, source) => sum + (source.updated ?? 0), 0);
  if (!added && !updated) return "Nothing changed since the last update.";
  return `${formatNumber(added)} new and ${formatNumber(updated)} updated trials.`;
}

const callbacks: LiveCallbacks = {
  onDataChanged: () =>
    notify.success("Data updated just now", {
      id: "data-updated",
      description: "Charts, lists and counts now show the new data.",
    }),
  onJobFinished: (job) => {
    const name = job.type.charAt(0).toUpperCase() + job.type.slice(1);
    if (job.status === "succeeded")
      notify.message(`${name} finished`, { description: summarize(job) });
    else if (job.status === "failed")
      notify.error(`${name} failed`, { description: job.error ?? undefined });
    else notify.message(`${name} cancelled`);
  },
};

export function LiveProvider({ children, url }: { children: ReactNode; url?: string }) {
  const queryClient = useQueryClient();
  const [live] = useState(() => new LiveEvents(queryClient, callbacks, url));
  useEffect(() => {
    live.connect();
    return () => live.close();
  }, [live]);
  return <LiveContext value={live}>{children}</LiveContext>;
}

export function useLiveEvents(): LiveEvents {
  const live = useContext(LiveContext);
  if (!live) throw new Error("useLive needs a LiveProvider");
  return live;
}

export function useLive<T>(select: (state: LiveState) => T): T {
  const live = useLiveEvents();
  return useSyncExternalStore(live.subscribe, () => select(live.getState()));
}
