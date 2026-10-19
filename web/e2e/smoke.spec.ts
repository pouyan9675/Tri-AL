/**
 * The smoke test (docs/design.md §11): dashboard → filter → trial detail → ⌘K, on the real
 * data. Counts are read from the API rather than written down, so a new release passes too.
 */
import { expect, type Page, test } from "@playwright/test";

const number = (value: number) => value.toLocaleString("en-US");

async function api<T>(page: Page, path: string): Promise<T> {
  const response = await page.request.get(path);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as T;
}

test("dashboard → filter → trial detail → ⌘K", async ({ page }) => {
  const meta = await api<{ trials: number }>(page, "/api/meta");
  const dashboard = await api<{ charts: { id: string; page: string }[] }>(page, "/api/dashboard");
  const charts = dashboard.charts.filter((chart) => chart.page === "dashboard");
  const recruiting = await api<{ total: number }>(
    page,
    "/api/facets?status=RECRUITING&fields=status&limit=1",
  );

  // Dashboard: every chart the API lists is drawn, the map included.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(
    page.getByText(`${number(meta.trials)} trials from ClinicalTrials.gov`),
  ).toBeVisible();
  const widgets = page.getByTestId("widget");
  await expect(widgets).toHaveCount(charts.length);
  await expect(page.locator('[data-testid="widget"][data-state="ready"]')).toHaveCount(
    charts.length,
  );
  await expect(page.locator('[data-widget="map"] svg[role="img"] path').first()).toBeVisible();
  await expect(page.getByText("Live", { exact: true })).toBeVisible(); // the event stream is open

  // Explorer: a facet filters the list and lands in the URL.
  await page.getByRole("link", { name: "Trials", exact: true }).click();
  await expect(page).toHaveURL(/\/trials$/);
  const table = page.getByTestId("trials-table");
  await expect(table.locator("tbody tr").first()).toBeVisible();
  await page
    .getByTestId("filter-panel")
    .getByLabel(/^Recruiting/)
    .check();
  await expect(page).toHaveURL(/status=RECRUITING/);
  await expect(
    page.getByText(`${number(recruiting.total)} of ${number(meta.trials)} trials match`),
  ).toBeVisible();
  await expect(page.getByTestId("filter-chips")).toContainText("Recruiting");
  await expect(table.locator("tbody tr").first()).toContainText("Recruiting");

  // Trial detail: the first trial, then its eligibility tab.
  const first = table.locator("tbody tr").first().getByRole("link").first();
  const title = (await first.textContent())?.trim() ?? "";
  await first.click();
  await expect(page).toHaveURL(/\/trials\/NCT\d{8}/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  await page.getByRole("tab", { name: "Eligibility" }).click();
  await expect(page).toHaveURL(/tab=eligibility/);
  await expect(page.getByText("Who can take part")).toBeVisible();
  await page.getByRole("tab", { name: /Locations/ }).click();
  await expect(page.getByRole("tabpanel")).toBeVisible();

  // ⌘K: search, then open the best hit with Enter.
  const detailUrl = page.url();
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("donanem"); // at once: no keystroke may be lost while it opens
  const input = page.getByRole("combobox");
  await expect(input).toBeFocused();
  await page.keyboard.type("ab"); // and the early text isn't selected, so this adds to it
  await expect(input).toHaveValue("donanemab");
  const results = page.getByTestId("palette-results");
  await expect(results.getByText("Trials", { exact: true })).toBeVisible();
  await expect(results.locator("mark").first()).toHaveText(/donanemab/i);
  await page.keyboard.press("Enter");
  await expect(page).not.toHaveURL(detailUrl);
  await expect(page).toHaveURL(/\/trials\/NCT\d{8}$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/donanemab/i);

  // A broad search says it ranked only the newest matches.
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("combobox").fill("study");
  await expect(page.getByTestId("capped-notice")).toBeVisible();
});

test("the analysis page draws the landscape in 3-D", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const rows = (
    await api<{ rows: { type: string; label?: string; embedded_trials?: number }[] }>(
      page,
      "/api/stats/research_landscape_3d",
    )
  ).rows;
  const [summary] = rows;
  const clusters = rows.filter((row) => row.type === "cluster");

  await page.goto("/");
  await page.getByRole("link", { name: "Analysis", exact: true }).click();
  await expect(page).toHaveURL(/\/analysis$/);
  const widget = page.locator('[data-widget="scatter3d"]');
  await expect(widget).toHaveAttribute("data-state", "ready");
  await expect(widget).toContainText(
    `${number(summary?.embedded_trials ?? 0)} trials first posted`,
  );
  const view = page.getByTestId("landscape-3d-canvas");
  await expect(view.locator("canvas")).toBeVisible();
  const list = page.getByRole("list", { name: "Clusters" });
  await expect(list.getByRole("button")).toHaveCount(clusters.length);

  // Stop it turning, then find a trial near the middle, where the map is densest.
  await page.getByRole("button", { name: "Stop turning" }).click();
  const box = await view.boundingBox();
  if (!box) throw new Error("the view has no box");
  let tooltip = false;
  for (const [dx, dy] of [
    [0, 0],
    [-40, 0],
    [40, 0],
    [0, -40],
    [0, 40],
    [-80, 30],
    [80, -30],
  ]) {
    await page.mouse.move(box.x + box.width / 2 + (dx ?? 0), box.y + box.height / 2 + (dy ?? 0));
    if (
      await page
        .getByRole("tooltip")
        .isVisible({ timeout: 1000 })
        .catch(() => false)
    ) {
      tooltip = true;
      break;
    }
  }
  expect(tooltip).toBe(true);
  await expect(page.getByRole("tooltip")).toContainText(/NCT\d{8}/);

  // A click pins it, with a link to the trial.
  await page.mouse.down();
  await page.mouse.up();
  const pinned = page.getByTestId("pinned-trial");
  await expect(pinned.getByRole("link", { name: /Open NCT\d{8}/ })).toBeVisible();

  // Choosing a cluster lights it up.
  const first = list.getByRole("button").first();
  await first.click();
  await expect(first).toHaveAttribute("aria-pressed", "true");
  await expect(first).toContainText(clusters[0]?.label ?? "");
  expect(errors).toEqual([]);
});

test("settings show the data, jobs and plugins", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByTestId("update-button")).toBeEnabled();
  await expect(page.getByTestId("plugins")).toContainText("charts");
  await expect(page.getByTestId("jobs-table").or(page.getByText("No jobs yet"))).toBeVisible();
});

test("a new data version over the event stream refreshes the page", async ({ page }) => {
  const meta = await api<{ data_version: number }>(page, "/api/meta");
  let announce = false;
  // The real stream only moves when an update commits; this one says the version moved.
  await page.route("**/api/events", (route) =>
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store" },
      body: [
        `event: hello\ndata: ${JSON.stringify({ data_version: meta.data_version, jobs: [] })}\n\n`,
        announce
          ? `event: data_version\ndata: ${JSON.stringify({ data_version: meta.data_version + 1 })}\n\n`
          : "",
        "retry: 500\n\n",
      ].join(""),
    }),
  );
  await page.goto("/");
  await expect(page.locator('[data-testid="widget"][data-state="ready"]').first()).toBeVisible();

  const refetched = page.waitForRequest((request) => request.url().includes("/api/stats/"));
  announce = true; // the next reconnect (retry: 500 ms) announces the new version
  await refetched;
  await expect(page.getByText("Data updated just now").first()).toBeVisible();
  await expect(page.getByTestId("data-status")).toHaveText("Data updated just now");
});
