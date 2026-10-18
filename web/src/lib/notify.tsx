/**
 * Toasts. sonner isn't in the first load: the toaster mounts once the page is idle (or at
 * the first toast), and each toast waits until it's there.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import type { ExternalToast } from "sonner";

const loadSonner = () => import("sonner");
const LazyToaster = lazy(() =>
  import("@/components/ui/sonner").then((module) => ({ default: module.Toaster })),
);

let wanted = false;
let requestMount: (() => void) | undefined;
let markReady: () => void = () => {};
const ready = new Promise<void>((resolve) => {
  markReady = resolve;
});

function Ready() {
  useEffect(() => markReady(), []);
  return null;
}

/** Mount once near the root. */
export function Toasts() {
  const [mounted, setMounted] = useState(wanted);
  useEffect(() => {
    requestMount = () => setMounted(true);
    if (wanted) setMounted(true);
    const idle =
      window.requestIdleCallback ?? ((callback: () => void) => setTimeout(callback, 2000));
    idle(() => setMounted(true));
    return () => {
      requestMount = undefined;
    };
  }, []);
  if (!mounted) return null;
  return (
    <Suspense fallback={null}>
      <LazyToaster position="bottom-right" />
      <Ready />
    </Suspense>
  );
}

type Kind = "message" | "success" | "error" | "info";

function show(kind: Kind, title: string, options?: ExternalToast): void {
  wanted = true;
  requestMount?.();
  void Promise.all([loadSonner(), ready]).then(([{ toast }]) => {
    if (kind === "message") toast(title, options);
    else toast[kind](title, options);
  });
}

export const notify = {
  message: (title: string, options?: ExternalToast) => show("message", title, options),
  success: (title: string, options?: ExternalToast) => show("success", title, options),
  error: (title: string, options?: ExternalToast) => show("error", title, options),
  info: (title: string, options?: ExternalToast) => show("info", title, options),
};
