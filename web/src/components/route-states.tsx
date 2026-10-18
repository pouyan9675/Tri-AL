import { type ErrorComponentProps, Link, useRouter } from "@tanstack/react-router";
import { CircleAlert, DatabaseZap, RotateCw, SearchX } from "lucide-react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";

export function NotFound() {
  return (
    <Empty className="m-auto">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SearchX />
        </EmptyMedia>
        <EmptyTitle>Nothing here</EmptyTitle>
        <EmptyDescription>This page doesn't exist. It may have moved.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button asChild variant="outline">
          <Link to="/">Back to the dashboard</Link>
        </Button>
      </EmptyContent>
    </Empty>
  );
}

/** An API or loading error, with what to do about it. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ApiError && error.status === 503) {
    return (
      <Empty className="m-auto">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <DatabaseZap />
          </EmptyMedia>
          <EmptyTitle>No data yet</EmptyTitle>
          <EmptyDescription>
            Install ClinicalTrials.gov first; it takes about 15 minutes. Run{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
              uv run tri-al install
            </code>{" "}
            and this page fills in by itself.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <Empty className="m-auto">
      <EmptyHeader>
        <EmptyMedia variant="icon">{notFound ? <SearchX /> : <CircleAlert />}</EmptyMedia>
        <EmptyTitle>{notFound ? "Not found" : "Something went wrong"}</EmptyTitle>
        <EmptyDescription>
          {error instanceof Error ? error.message : "The request failed."}
        </EmptyDescription>
      </EmptyHeader>
      {onRetry && !notFound && (
        <EmptyContent>
          <Button variant="outline" onClick={onRetry}>
            <RotateCw /> Try again
          </Button>
        </EmptyContent>
      )}
    </Empty>
  );
}

export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  return (
    <ErrorState
      error={error}
      onRetry={() => {
        reset();
        void router.invalidate();
      }}
    />
  );
}
