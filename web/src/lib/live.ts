/**
 * The live event stream (`/api/events`): one `EventSource` for the whole app.
 *
 * - `hello` brings the data version and the active jobs. After a reconnect, a version that
 *   moved while the stream was down refreshes the data too.
 * - `data_version` means an update or install committed: every data query is invalidated,
 *   so mounted pages refetch (304s for whatever didn't change) and keep showing the old data
 *   until the new arrives.
 * - `job` is a job as it is now; it's merged into the cached job list, so job progress needs
 *   no polling. When one finishes, the meta (its last run) is fetched again.
 */
import type { QueryClient } from "@tanstack/react-query";
import type { Job } from "@/api/client";
import { DATA_KEY, JOBS_KEY, JOBS_LIMIT } from "@/api/queries";

export type LiveStatus = "connecting" | "open" | "closed";

export type LiveState = {
  status: LiveStatus;
  dataVersion: number | null;
  /** When the data version last changed while the page was open (ms since the epoch). */
  dataChangedAt: number | null;
  /** Jobs the stream has reported, by id: the active ones and those that finished since. */
  jobs: Record<number, Job>;
};

export type LiveCallbacks = {
  onDataChanged?: (dataVersion: number) => void;
  onJobFinished?: (job: Job) => void;
};

const FINISHED = new Set<Job["status"]>(["succeeded", "failed", "cancelled"]);

export function isActive(job: Job): boolean {
  return job.status === "queued" || job.status === "running";
}

type JobList = { jobs: Job[] };

function upsert(list: Job[], job: Job): Job[] {
  const index = list.findIndex((item) => item.id === job.id);
  if (index === -1) return [job, ...list].sort((a, b) => b.id - a.id).slice(0, JOBS_LIMIT);
  const next = [...list];
  next[index] = job;
  return next;
}

export class LiveEvents {
  private state: LiveState = { status: "closed", dataVersion: null, dataChangedAt: null, jobs: {} };
  private readonly listeners = new Set<() => void>();
  private source: EventSource | null = null;

  constructor(
    private readonly queryClient: QueryClient,
    private readonly callbacks: LiveCallbacks = {},
    private readonly url = "/api/events",
  ) {}

  getState = (): LiveState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private set(partial: Partial<LiveState>): void {
    this.state = { ...this.state, ...partial };
    for (const listener of this.listeners) listener();
  }

  connect(): void {
    if (this.source || typeof EventSource === "undefined") return;
    this.set({ status: "connecting" });
    const source = new EventSource(this.url);
    this.source = source;
    source.addEventListener("open", () => this.set({ status: "open" }));
    // EventSource reconnects by itself; until then the page says it's offline.
    source.addEventListener("error", () =>
      this.set({ status: source.readyState === EventSource.CLOSED ? "closed" : "connecting" }),
    );
    source.addEventListener("hello", (event) => this.hello(JSON.parse(event.data)));
    source.addEventListener("data_version", (event) =>
      this.dataVersion(JSON.parse(event.data).data_version),
    );
    source.addEventListener("job", (event) => this.job(JSON.parse(event.data)));
  }

  close(): void {
    this.source?.close();
    this.source = null;
    this.set({ status: "closed" });
  }

  hello(data: { data_version: number; jobs: Job[] }): void {
    const jobs = { ...this.state.jobs };
    for (const job of data.jobs) jobs[job.id] = job;
    const previous = this.state.dataVersion;
    this.set({ status: "open", jobs });
    if (previous === null) this.set({ dataVersion: data.data_version });
    else this.dataVersion(data.data_version);
    for (const job of data.jobs) this.mergeJob(job);
  }

  dataVersion(version: number): void {
    if (version === this.state.dataVersion) return;
    const known = this.state.dataVersion !== null;
    this.set({
      dataVersion: version,
      dataChangedAt: known ? Date.now() : this.state.dataChangedAt,
    });
    if (!known) return;
    void this.queryClient.invalidateQueries({ queryKey: DATA_KEY });
    this.callbacks.onDataChanged?.(version);
  }

  job(job: Job): void {
    const before = this.state.jobs[job.id];
    this.set({ jobs: { ...this.state.jobs, [job.id]: job } });
    this.mergeJob(job);
    if (FINISHED.has(job.status) && before && !FINISHED.has(before.status)) {
      // A run that changed nothing keeps the data version, but the meta's last run moved.
      void this.queryClient.invalidateQueries({ queryKey: [...DATA_KEY, "meta"] });
      this.callbacks.onJobFinished?.(job);
    }
  }

  private mergeJob(job: Job): void {
    const cached = this.queryClient.getQueryData<JobList>(JOBS_KEY);
    if (cached)
      this.queryClient.setQueryData<JobList>(JOBS_KEY, { jobs: upsert(cached.jobs, job) });
    else void this.queryClient.invalidateQueries({ queryKey: JOBS_KEY });
  }
}
