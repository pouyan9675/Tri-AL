import { Link, Outlet, useMatches } from "@tanstack/react-router";
import { ChevronRight, SearchIcon } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { DataStatus } from "@/components/data-status";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";

const loadPalette = () => import("@/components/command-palette");
const CommandPalette = lazy(loadPalette);

function sidebarOpen(): boolean {
  return !document.cookie.split("; ").includes("sidebar_state=false");
}

export function AppShell() {
  const [palette, setPalette] = useState<"closed" | "open" | "unloaded">("unloaded");
  // What's typed between ⌘K and the palette's input taking focus (its chunk may still be
  // loading), handed to the palette so no keystroke is lost.
  const typed = useRef<string | null>(null);
  const openPalette = useCallback(() => {
    typed.current = "";
    setPalette("open");
  }, []);
  const takeTyped = useCallback(() => {
    const text = typed.current ?? "";
    typed.current = null;
    return text;
  }, []);

  // Not in the first load, but fetched once the page is idle, so ⌘K opens at once.
  useEffect(() => {
    const idle =
      window.requestIdleCallback ?? ((callback: () => void) => setTimeout(callback, 1500));
    idle(() => void loadPalette());
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setPalette((state) => {
          typed.current = state === "open" ? null : "";
          return state === "open" ? "closed" : "open";
        });
        return;
      }
      if (typed.current === null || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key.length === 1) typed.current += event.key;
      else if (event.key === "Backspace") typed.current = typed.current.slice(0, -1);
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, []);

  return (
    <SidebarProvider defaultOpen={sidebarOpen()}>
      <AppSidebar onSearch={openPalette} onSearchIntent={loadPalette} />
      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur-md supports-[backdrop-filter]:bg-background/70 sm:px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
          <Breadcrumbs />
          <div className="ml-auto flex items-center gap-1.5">
            <Button
              variant="outline"
              className="hidden h-8 w-56 justify-start gap-2 bg-muted/40 px-2.5 font-normal text-muted-foreground shadow-none hover:bg-muted md:flex lg:w-64"
              onClick={openPalette}
              onPointerEnter={loadPalette}
              onFocus={loadPalette}
            >
              <SearchIcon className="size-4" />
              <span>Search trials or IDs…</span>
              <Kbd className="ml-auto">⌘K</Kbd>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label="Search"
              onClick={openPalette}
            >
              <SearchIcon />
            </Button>
            <DataStatus />
            <ThemeToggle />
          </div>
        </header>
        <div className="flex min-w-0 flex-1 flex-col">
          <Outlet />
        </div>
      </SidebarInset>
      {palette !== "unloaded" && (
        <Suspense fallback={null}>
          <CommandPalette
            open={palette === "open"}
            onOpenChange={(open) => {
              if (!open) typed.current = null;
              setPalette(open ? "open" : "closed");
            }}
            takeTyped={takeTyped}
          />
        </Suspense>
      )}
    </SidebarProvider>
  );
}

function Breadcrumbs() {
  const matches = useMatches();
  const leaf = matches[matches.length - 1];
  const title = leaf?.staticData.title;
  const sourceId = (leaf?.params as { sourceId?: string } | undefined)?.sourceId;
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
      {sourceId ? (
        <>
          <Link
            to="/trials"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            Trials
          </Link>
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" />
          <span className="truncate font-mono text-[0.8rem] font-medium">{sourceId}</span>
        </>
      ) : (
        <span className="truncate font-medium">{title}</span>
      )}
    </nav>
  );
}
