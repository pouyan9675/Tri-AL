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
  const dashboard = await api<{ charts: { id: string }[] }>(page, "/api/dashboard");
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
  await expect(widgets).toHaveCount(dashboard.charts.length);
  await expect(page.locator('[data-testid="widget"][data-state="ready"]')).toHaveCount(
    dashboard.charts.length,
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
