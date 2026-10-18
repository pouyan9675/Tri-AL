import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { Job } from "@/api/client";
import { DATA_KEY, JOBS_KEY } from "@/api/queries";
import { LiveEvents } from "./live";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    type: "update",
    status: "running",
    origin: "api",
    stage: "fetch",
    progress: 1000,
    total: 2606,
    unit: "trials",
    message: null,
    error: null,
    cancel_requested: false,
    created_at: "2026-10-18T10:00:00+00:00",
    started_at: "2026-10-18T10:00:01+00:00",
    finished_at: null,
    heartbeat: null,
    result: null,
    ...overrides,
  };
}

function setup() {
  const queryClient = new QueryClient();
  const onDataChanged = vi.fn();
  const onJobFinished = vi.fn();
  const live = new LiveEvents(queryClient, { onDataChanged, onJobFinished });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  return { queryClient, live, onDataChanged, onJobFinished, invalidate };
}

describe("the live event stream", () => {
  it("learns the data version from hello without refetching", () => {
    const { live, invalidate, onDataChanged } = setup();
    live.hello({ data_version: 3, jobs: [] });
    expect(live.getState().dataVersion).toBe(3);
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: DATA_KEY });
    expect(onDataChanged).not.toHaveBeenCalled();
  });

  it("invalidates every data query when the version changes", () => {
    const { live, invalidate, onDataChanged } = setup();
    live.hello({ data_version: 3, jobs: [] });
    live.dataVersion(4);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: DATA_KEY });
    expect(onDataChanged).toHaveBeenCalledWith(4);
    expect(live.getState().dataChangedAt).not.toBeNull();
  });

  it("catches up after a reconnect when the version moved meanwhile", () => {
    const { live, onDataChanged } = setup();
    live.hello({ data_version: 3, jobs: [] });
    live.hello({ data_version: 5, jobs: [] });
    expect(onDataChanged).toHaveBeenCalledWith(5);
  });

  it("merges job progress into the cached job list", () => {
    const { live, queryClient } = setup();
    queryClient.setQueryData(JOBS_KEY, { jobs: [job({ id: 6, status: "succeeded" })] });
    live.job(job());
    live.job(job({ progress: 2000 }));
    const { jobs } = queryClient.getQueryData<{ jobs: Job[] }>(JOBS_KEY) ?? { jobs: [] };
    expect(jobs.map((item) => [item.id, item.progress])).toEqual([
      [7, 2000],
      [6, 1000],
    ]);
  });

  it("reports a job that finishes, and refreshes the meta's last run", () => {
    const { live, onJobFinished, invalidate } = setup();
    live.job(job());
    live.job(job({ status: "succeeded", finished_at: "2026-10-18T10:00:09+00:00" }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: [...DATA_KEY, "meta"] });
    expect(onJobFinished).toHaveBeenCalledTimes(1);
    expect(onJobFinished.mock.calls[0]?.[0].status).toBe("succeeded");
  });
});
