/**
 * Query options for the AI engine: its settings, and annotating a trial text. Apart from
 * `queries.ts` so they load with the pages that use them, not with the app's first load.
 */
import { queryOptions, experimental_streamedQuery as streamedQuery } from "@tanstack/react-query";
import { type Annotation, EMPTY_ANNOTATION, withEvent } from "@/lib/annotations";
import { type AnnotatedField, type AnnotationEvent, ApiError, api, detail, unwrap } from "./client";

/** The values of a newline-delimited JSON body, each as soon as its line arrives. */
export async function* jsonLines<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = done ? "" : (lines.pop() ?? "");
      for (const line of lines) if (line.trim()) yield JSON.parse(line) as T;
      if (done) return;
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}

export const AI_KEY = ["ai"] as const;

export const aiSettingsQuery = () =>
  queryOptions({
    queryKey: [...AI_KEY, "settings"],
    queryFn: ({ signal }) => unwrap(api.GET("/api/ai", { signal })),
    staleTime: 30_000,
  });

/**
 * A trial text's annotations, filled in as the model finishes each piece of it. Nothing runs
 * until `refetch()`; `version` (the settings and the data version) keeps results apart.
 */
export const annotationQuery = (sourceId: string, field: AnnotatedField, version: string) =>
  queryOptions({
    queryKey: [...AI_KEY, "annotation", sourceId, field, version],
    queryFn: streamedQuery<AnnotationEvent, Annotation>({
      streamFn: async function* ({ signal }) {
        const { data, error, response } = await api.POST("/api/trials/{source_id}/annotate", {
          params: { path: { source_id: sourceId } },
          body: { field },
          parseAs: "stream",
          signal,
        });
        if (!response.ok || !data) {
          throw new ApiError(response.status, detail(error, response.status), error);
        }
        for await (const event of jsonLines<AnnotationEvent>(data)) {
          if (event.type === "error") throw new ApiError(502, event.message);
          yield event;
        }
      },
      reducer: withEvent,
      initialValue: EMPTY_ANNOTATION,
    }),
    enabled: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 30 * 60_000,
  });
