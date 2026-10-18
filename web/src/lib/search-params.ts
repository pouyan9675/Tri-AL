/**
 * The router's URL search format: plain `URLSearchParams`, a key repeated for several
 * values, which is also the API's query format. (TanStack Router's default writes JSON.)
 */

export function parseSearch(search: string): Record<string, unknown> {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const out: Record<string, string | string[]> = {};
  for (const [key, value] of params) {
    const current = out[key];
    if (current === undefined) out[key] = value;
    else out[key] = Array.isArray(current) ? [...current, value] : [current, value];
  }
  return out;
}

export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item === undefined || item === null || item === "") continue;
      params.append(key, String(item));
    }
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}
