import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiError } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LiveProvider } from "@/lib/live-context";
import { Toasts } from "@/lib/notify";
import { ThemeProvider } from "@/lib/theme";
import { makeRouter } from "@/router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // A 4xx won't change by asking again; a network blip might.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});
const router = makeRouter(queryClient);

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <LiveProvider>
          <TooltipProvider delayDuration={300}>
            <RouterProvider router={router} />
            <Toasts />
          </TooltipProvider>
        </LiveProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
