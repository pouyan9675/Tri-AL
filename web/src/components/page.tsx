import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A page's frame: title, description and actions above its content. */
export function Page({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <main
      className={cn(
        "mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-6 p-4 sm:p-6",
        className,
      )}
    >
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
          {description && <div className="text-sm text-muted-foreground">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </main>
  );
}
