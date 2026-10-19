/**
 * Annotations of a trial text: the stream's events folded into one state, and the spans
 * placed on the text as `TextBlocks` shows it.
 *
 * Span offsets count characters of the field's text with line breaks as `\n`. `TextBlocks`
 * trims lines and joins a paragraph's lines with spaces, so each block keeps a map from its
 * own text back to the source (`Piece`), and `marksFor` follows it.
 */
import type { AnnotationEvent, AnnotationLabelRef, AnnotationSpan, LabelColor } from "@/api/client";

export type Annotation = {
  model: string | null;
  /** Characters of text the offsets refer to. */
  length: number | null;
  /** Pieces the text was cut into, each its own request; 0 until the stream starts. */
  chunks: number;
  /** Pieces answered so far. */
  received: number;
  cached: boolean;
  labels: AnnotationLabelRef[];
  /** In text order. */
  spans: AnnotationSpan[];
  /** Set when the stream has ended. */
  seconds: number | null;
};

export const EMPTY_ANNOTATION: Annotation = {
  model: null,
  length: null,
  chunks: 0,
  received: 0,
  cached: false,
  labels: [],
  spans: [],
  seconds: null,
};

export function withEvent(state: Annotation, event: AnnotationEvent): Annotation {
  switch (event.type) {
    case "start":
      return {
        ...EMPTY_ANNOTATION,
        model: event.model,
        length: event.length,
        chunks: event.chunks,
        cached: event.cached,
        labels: event.labels,
      };
    case "spans":
      return {
        ...state,
        received: state.received + 1,
        spans: [...state.spans, ...event.spans].sort((a, b) => a.start - b.start),
      };
    case "done":
      return { ...state, received: state.chunks, seconds: event.seconds };
    default:
      return state;
  }
}

/** The text a field's offsets refer to, as the API reads it. */
export function sourceText(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** A block's `text[at, at + len)` is the source's `[src, src + len)`. */
export type Piece = { at: number; src: number; len: number };

/** A span placed on a block's text. */
export type Mark = { start: number; end: number; label: string };

/** Where `spans` fall in a block's text; a span over a line break stays one mark. */
export function marksFor(map: Piece[], spans: readonly AnnotationSpan[]): Mark[] {
  const first = map[0];
  const last = map[map.length - 1];
  if (!first || !last) return [];
  const from = first.src;
  const to = last.src + last.len;
  const out: Mark[] = [];
  for (const span of spans) {
    if (span.end <= from || span.start >= to) continue;
    let mark: Mark | undefined;
    for (const piece of map) {
      const start = Math.max(span.start, piece.src);
      const end = Math.min(span.end, piece.src + piece.len);
      if (start >= end) continue;
      const at = piece.at + start - piece.src;
      if (mark && at - mark.end <= 1) mark.end = piece.at + end - piece.src;
      else {
        mark = { start: at, end: piece.at + end - piece.src, label: span.label };
        out.push(mark);
      }
    }
  }
  return out.sort((a, b) => a.start - b.start);
}

/** Each label colour's classes, from the chart palette, so both themes have them. */
export const LABEL_TONES: Record<LabelColor, { mark: string; dot: string }> = {
  blue: { mark: "bg-chart-1/15 decoration-chart-1/70", dot: "bg-chart-1" },
  orange: { mark: "bg-chart-2/15 decoration-chart-2/70", dot: "bg-chart-2" },
  teal: { mark: "bg-chart-3/15 decoration-chart-3/70", dot: "bg-chart-3" },
  amber: { mark: "bg-chart-4/18 decoration-chart-4/80", dot: "bg-chart-4" },
  pink: { mark: "bg-chart-5/18 decoration-chart-5/80", dot: "bg-chart-5" },
  green: { mark: "bg-chart-6/15 decoration-chart-6/70", dot: "bg-chart-6" },
  violet: { mark: "bg-chart-7/15 decoration-chart-7/70", dot: "bg-chart-7" },
  red: { mark: "bg-chart-8/15 decoration-chart-8/70", dot: "bg-chart-8" },
};
