/**
 * Registry text as readable blocks. ClinicalTrials.gov text is plain, with markdown-like
 * habits: blank lines between paragraphs, `*` or `-` bullets (indented for nesting), and
 * headings such as "Inclusion Criteria:".
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: { id: number; text: string; depth: number }[] };

const BULLET = /^(\s*)(?:[*\-•·]|\d+[.)])\s+(.*)$/;
const HEADING = /^[A-Z][^.!?]{2,80}:$/;

export function blocks(text: string): Block[] {
  const out: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) out.push({ kind: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }
    const bullet = BULLET.exec(line);
    if (bullet) {
      flush();
      const depth = Math.min(3, Math.floor((bullet[1]?.length ?? 0) / 2));
      const last = out[out.length - 1];
      const item = {
        id: out.length * 1000 + (last?.kind === "list" ? last.items.length : 0),
        text: (bullet[2] ?? "").trim(),
        depth,
      };
      if (last?.kind === "list") last.items.push(item);
      else out.push({ kind: "list", items: [item] });
      continue;
    }
    if (HEADING.test(line.trim())) {
      flush();
      out.push({ kind: "heading", text: line.trim().replace(/:$/, "") });
      continue;
    }
    const last = out[out.length - 1];
    if (!paragraph.length && last?.kind === "list" && /^\s/.test(raw)) {
      // A wrapped bullet: an indented line right after one.
      const item = last.items[last.items.length - 1];
      if (item) item.text += ` ${line.trim()}`;
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return out;
}

export function TextBlocks({
  text,
  className,
}: {
  text: string | null | undefined;
  className?: string;
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
              {block.text}
            </h4>
          );
        }
        if (block.kind === "paragraph") return <p key={key}>{block.text}</p>;
        return (
          <ul key={key} className="space-y-1.5">
            {block.items.map((item) => (
              <li key={item.id} className="flex gap-2.5" style={{ paddingLeft: item.depth * 18 }}>
                <span className="mt-[0.6em] size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        );
      })}
    </div>
  );
}
