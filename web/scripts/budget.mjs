#!/usr/bin/env node
/**
 * The front-end bundle budget (docs/design.md §10): initial JS under 200 KB gzip.
 *
 * "Initial" is what the browser must load before any page can render: the entry chunk and
 * every chunk it imports statically. Each page's own chunks load after it, so they are
 * reported too, with the total a cold load of that page costs. Run after `npm run build`.
 *
 *   node scripts/budget.mjs          # table; exit 1 when over budget
 *   node scripts/budget.mjs --json   # the same as JSON
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET_KB = 200;
const dist = join(import.meta.dirname, "..", "dist");
const manifest = JSON.parse(readFileSync(join(dist, ".vite", "manifest.json"), "utf8"));

const gzip = (file) => gzipSync(readFileSync(join(dist, file)), { level: 9 }).length;

/** The chunk for `key` and every chunk it imports statically, as file names. */
function closure(key, seen = new Set()) {
  const chunk = manifest[key];
  if (!chunk || seen.has(chunk.file)) return seen;
  seen.add(chunk.file);
  for (const imported of chunk.imports ?? []) closure(imported, seen);
  return seen;
}

const kb = (bytes) => bytes / 1024;
const total = (files) => [...files].reduce((sum, file) => sum + gzip(file), 0);

const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry);
const initial = closure(entryKey);
const initialBytes = total(initial);

/** Lazy chunks, and the chunk that loads each (so what's already there isn't counted). */
const PAGES = {
  dashboard: ["src/pages/dashboard/index.tsx"],
  "  + map widget": ["src/widgets/map.tsx", "src/pages/dashboard/index.tsx"],
  trials: ["src/pages/trials/index.tsx"],
  trial: ["src/pages/trial/index.tsx"],
  settings: ["src/pages/settings/index.tsx"],
  "⌘K palette": ["src/components/command-palette.tsx"],
};

const pages = Object.entries(PAGES).map(([name, [key, after]]) => {
  const loaded = after ? new Set([...initial, ...closure(after)]) : initial;
  const own = [...closure(key)].filter((file) => !loaded.has(file));
  return { name: name.trim(), kb: kb(total(own)), coldKb: kb(total(loaded) + total(own)) };
});
const css = Object.values(manifest)
  .flatMap((chunk) => chunk.css ?? [])
  .filter((file, index, all) => all.indexOf(file) === index);

const report = {
  budgetKb: BUDGET_KB,
  initialKb: kb(initialBytes),
  initialFiles: [...initial],
  cssKb: kb(total(css)),
  pages,
};

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(report, null, 2));
} else {
  const f = (value) => `${value.toFixed(1)} KB`.padStart(9);
  console.log(
    `Initial JS (entry + static imports): ${f(report.initialKb)} gzip   budget ${BUDGET_KB} KB`,
  );
  console.log(`CSS:                                 ${f(report.cssKb)} gzip`);
  console.log("\nLoaded on demand          own gzip   cold load total");
  for (const page of pages)
    console.log(`  ${page.name.padEnd(20)} ${f(page.kb)}   ${f(page.coldKb)}`);
}

if (report.initialKb > BUDGET_KB) {
  console.error(
    `\nOver budget: initial JS is ${report.initialKb.toFixed(1)} KB gzip (budget ${BUDGET_KB} KB).`,
  );
  process.exit(1);
}
