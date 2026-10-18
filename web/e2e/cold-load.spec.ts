/**
 * The dashboard's cold-load budget (docs/design.md §10): interactive in under 1.5 s.
 *
 * Each run is a new browser context (empty cache, no service worker), loading `/` from
 * `tri-al serve`. "Interactive" is when every chart from `/api/dashboard` has drawn, the
 * map included, measured from the start of navigation. Also recorded: first contentful
 * paint, and the JavaScript fetched by then as sent (gzip). Run alone with
 *
 *   npx playwright test cold-load
 */
import { expect, test } from "@playwright/test";

const RUNS = 5;
const BUDGET_MS = 1500;

type Run = { interactiveMs: number; fcpMs: number; jsKb: number; requests: number };

async function coldLoad(
  browser: import("@playwright/test").Browser,
  cpuSlowdown = 1,
): Promise<Run> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  if (cpuSlowdown > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: cpuSlowdown });
  const types = new Map<string, string>();
  let jsBytes = 0;
  let requests = 0;
  cdp.on("Network.responseReceived", (event) => types.set(event.requestId, event.type));
  cdp.on("Network.loadingFinished", (event) => {
    requests += 1;
    if (types.get(event.requestId) === "Script") jsBytes += event.encodedDataLength;
  });

  const charts = (await (await page.request.get("/api/dashboard")).json()).charts.length as number;
  await page.goto("/", { waitUntil: "commit" });
  const interactiveMs = await page.evaluate(
    (count) =>
      new Promise<number>((resolve) => {
        const done = () =>
          document.querySelectorAll('[data-testid="widget"][data-state="ready"]').length ===
            count && document.querySelector('[data-widget="map"] svg[role="img"] path') !== null;
        const check = () => (done() ? resolve(performance.now()) : requestAnimationFrame(check));
        check();
      }),
    charts,
  );
  const jsKb = jsBytes / 1024; // what had loaded by then; the palette and toasts come later
  const fcpMs = await page.evaluate(
    () => performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? 0,
  );
  await context.close();
  return { interactiveMs, fcpMs, jsKb, requests };
}

const median = (values: number[]) =>
  [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)] ?? 0;

test("the dashboard is interactive within 1.5 s on a cold load", async ({ browser }) => {
  await coldLoad(browser); // warm the server (and the OS file cache), not the browser
  const runs: Run[] = [];
  for (let index = 0; index < RUNS; index += 1) runs.push(await coldLoad(browser));
  const slow = await coldLoad(browser, 4);

  const summary = {
    runs: RUNS,
    interactiveMedianMs: Math.round(median(runs.map((run) => run.interactiveMs))),
    interactiveMaxMs: Math.round(Math.max(...runs.map((run) => run.interactiveMs))),
    fcpMedianMs: Math.round(median(runs.map((run) => run.fcpMs))),
    jsKbOverTheWire: Number(median(runs.map((run) => run.jsKb)).toFixed(1)),
    requests: median(runs.map((run) => run.requests)),
    cpu4xInteractiveMs: Math.round(slow.interactiveMs),
  };
  console.log(`cold load: ${JSON.stringify(summary)}`);
  test.info().annotations.push({ type: "cold-load", description: JSON.stringify(summary) });
  expect(summary.interactiveMaxMs).toBeLessThan(BUDGET_MS);
});
