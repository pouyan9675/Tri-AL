/** A snippet of a trial's text with the words a search matched marked. */
import type { Schemas } from "@/api/client";
import { cn } from "@/lib/utils";

type Part = Schemas["SnippetPartOut"];

export const MARK = "rounded-[3px] bg-brand/15 px-0.5 text-foreground dark:bg-brand/30";

/** Snippet parts with their offset in the snippet, which keys them. */
function withOffsets(parts: Part[]) {
  let at = 0;
  return parts.map((part) => {
    const item = { ...part, at };
    at += part.text.length;
    return item;
  });
}

export function Snippet({ parts, className }: { parts: Part[]; className?: string }) {
  return (
    <span className={cn("text-xs leading-relaxed text-muted-foreground", className)}>
      {withOffsets(parts).map((part) =>
        part.match ? (
          <mark key={part.at} className={MARK}>
            {part.text}
          </mark>
        ) : (
          <span key={part.at}>{part.text}</span>
        ),
      )}
    </span>
  );
}
