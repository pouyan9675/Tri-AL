import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Job } from "@/api/client";
import { JobProgress } from "./job-progress";

const RUNNING: Job = {
  id: 9,
  type: "update",
  status: "running",
  origin: "api",
  stage: "write",
  progress: 1303,
  total: 2606,
  unit: "trials",
  message: null,
  error: null,
  cancel_requested: false,
  created_at: "2026-10-18T10:00:00+00:00",
  started_at: new Date(Date.now() - 4000).toISOString(),
  finished_at: null,
  heartbeat: null,
  result: null,
};

describe("job progress", () => {
  it("shows the stage, how far along it is, and a cancel button", async () => {
    const cancel = vi.fn();
    render(<JobProgress job={RUNNING} onCancel={cancel} />);
    expect(screen.getByText("Update · Writing trials")).toBeInTheDocument();
    expect(screen.getByText("1,303 trials of 2,606 trials")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalled();
  });

  it("shows a queued job as waiting, with no bar until there's a total", () => {
    render(
      <JobProgress
        job={{
          ...RUNNING,
          status: "queued",
          stage: null,
          total: null,
          progress: 0,
          started_at: null,
        }}
      />,
    );
    expect(screen.getByText("Update · Waiting for the worker")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
