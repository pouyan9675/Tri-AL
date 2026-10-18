import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/lib/theme";

export function testQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Number.POSITIVE_INFINITY } },
  });
}

/** `ui` with the providers every page has (no router, no event stream). */
export function renderWithProviders(ui: ReactNode, queryClient = testQueryClient()) {
  const result = render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>{ui}</TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { ...result, queryClient };
}
