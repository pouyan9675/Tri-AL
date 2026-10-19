/**
 * Registry text as readable blocks. ClinicalTrials.gov text is plain, with markdown-like
 * habits: blank lines between paragraphs, `*` or `-` bullets (indented for nesting), and
 * headings such as "Inclusion Criteria:".
 *
 * Each block keeps a map back to the source text, so annotations (offsets in the source)
 * can be drawn on it.
 */
import type { ReactNode } from "react";
import type { AnnotationSpan, LabelColor } from "@/api/client";
import { LABEL_TONES, marksFor, type Piece } from "@/lib/annotations";
import { cn } from "@/lib/utils";

type Item = { id: number; text: string; depth: number; map: Piece[] };

type Block =
  | { kind: "heading"; text: string; map: Piece[] }
  | { kind: "paragraph"; text: string; map: Piece[] }
  | { kind: "list"; items: Item[] };

const BULLET = /^(\s*)(?:[*\-•·]|\d+[.)])\s+(.*)$/;
const HEADING = /^[A-Z][^.!?]{2,80}:$/;

type Line = { text: string; src: number };

function joined(lines: Line[]): { text: string; map: Piece[] } {
  let text = "";
  const map: Piece[] = [];
  for (const line of lines) {
    if (text) text += " ";
    map.push({ at: text.length, src: line.src, len: line.text.length });
    text += line.text;
  }
  return { text, map };
}

export function blocks(source: string): Block[] {
  const out: Block[] = [];
  let paragraph: Line[] = [];
  const flush = () => {
    if (paragraph.length) out.push({ kind: "paragraph", ...joined(paragraph) });
    paragraph = [];
  };
  let offset = 0;
  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const start = offset;
    offset += raw.length + 1;
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }
    const src = start + line.length - line.trimStart().length;
    const bullet = BULLET.exec(line);
    if (bullet) {
      flush();
      const depth = Math.min(3, Math.floor((bullet[1]?.length ?? 0) / 2));
      const text = bullet[2] ?? "";
      const last = out[out.length - 1];
      const item = {
        id: out.length * 1000 + (last?.kind === "list" ? last.items.length : 0),
        text,
        depth,
        map: [{ at: 0, src: start + line.length - text.length, len: text.length }],
      };
      if (last?.kind === "list") last.items.push(item);
      else out.push({ kind: "list", items: [item] });
      continue;
    }
    const text = line.trim();
    if (HEADING.test(text)) {
      flush();
      const heading = text.replace(/:$/, "");
      out.push({ kind: "heading", text: heading, map: [{ at: 0, src, len: heading.length }] });
      continue;
    }
    const last = out[out.length - 1];
    if (!paragraph.length && last?.kind === "list" && /^\s/.test(raw)) {
      // A wrapped bullet: an indented line right after one.
      const item = last.items[last.items.length - 1];
      if (item) {
        item.map.push({ at: item.text.length + 1, src, len: text.length });
        item.text += ` ${text}`;
      }
      continue;
    }
    paragraph.push({ text, src });
  }
  flush();
  return out;
}

/** Spans to draw on the text, and the colour of each label. */
export type Marks = {
  spans: readonly AnnotationSpan[];
  colors: Readonly<Record<string, LabelColor>>;
};

function Marked({ text, map, marks }: { text: string; map: Piece[]; marks?: Marks }) {
  if (!marks?.spans.length) return text;
  const parts: ReactNode[] = [];
  let at = 0;
  for (const mark of marksFor(map, marks.spans)) {
    const color = marks.colors[mark.label];
    if (!color || mark.start < at) continue;
    if (mark.start > at) parts.push(text.slice(at, mark.start));
    parts.push(
      <mark
        key={mark.start}
        title={mark.label}
        data-label={mark.label}
        className={cn(
          "rounded-[3px] px-px text-inherit underline decoration-2 underline-offset-[3px] animate-in duration-500 fade-in",
          LABEL_TONES[color].mark,
        )}
      >
        {text.slice(mark.start, mark.end)}
      </mark>,
    );
    at = mark.end;
  }
  parts.push(text.slice(at));
  return parts;
}

export function TextBlocks({
  text,
  className,
  marks,
}: {
  text: string | null | undefined;
  className?: string;
  marks?: Marks;
}) {
  if (!text?.trim()) return <p className="text-sm text-muted-foreground">Not given.</p>;
  return (
    <div className={cn("space-y-3 text-sm leading-relaxed text-foreground/90", className)}>
      {blocks(text).map((block, index): ReactNode => {
        const key = `${block.kind}-${index}`;
        if (block.kind === "heading") {
          return (
            <h4
              key={key}
              className="pt-1 text-[0.8rem] font-semibold tracking-wide text-foreground uppercase"
            >
              <Marked text={block.text} map={block.map} marks={marks} />
            </h4>
          );
        }
        if (block.kind === "paragraph") {
          return (
            <p key={key}>
              <Marked text={block.text} map={block.map} marks={marks} />
            </p>
          );
        }
        return (
          <ul key={key} className="space-y-1.5">
            {block.items.map((item) => (
              <li key={item.id} className="flex gap-2.5" style={{ paddingLeft: item.depth * 18 }}>
                <span className="mt-[0.6em] size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                <span>
                  <Marked text={item.text} map={item.map} marks={marks} />
                </span>
              </li>
            ))}
          </ul>
        );
      })}
    </div>
  );
}
