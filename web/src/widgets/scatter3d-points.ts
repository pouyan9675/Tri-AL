/**
 * The 3-D landscape's points, apart from WebGL: which colour and size each is drawn in, how
 * the view is framed, and which one is under the pointer. Pure, so tests needn't load three.js.
 */

export type RGB = readonly [number, number, number];

/** Colours from the theme, as sRGB in 0..1: the 8 chart colours, then the neutrals. */
export type Palette = { chart: RGB[]; muted: RGB; foreground: RGB };

/** What a point's colour stands for: 0 to 7 a chart colour, or one of these. */
export const GREY = 8; // a cluster without a colour
export const FAINT = 9; // in no cluster
export const GHOST = 10; // context behind a filter: not pickable
export const NO_CLUSTER = -2147483648; // a cluster id no highlight matches

export type Cloud = {
  positions: Float32Array; // x, y, z per point, most within the unit sphere
  slots: Uint8Array; // colour slot per point
  clusters: Int32Array; // cluster per point, for highlighting
};

const ALPHA: Record<number, number> = { [GREY]: 0.4, [FAINT]: 0.2, [GHOST]: 0.05 };
/** Over the faint rest of the map, a filter's trials in grey clusters are drawn stronger. */
const ALPHA_IN_FRONT: Record<number, number> = { [GREY]: 0.7, [FAINT]: 0.5 };
const COLOURED_ALPHA = 0.85;
const FADED_ALPHA = 0.05; // the other clusters while one is highlighted
export const FOV = 40;
/** The server scales the layout so 99% of trials are within 1; the view frames that. */
export const RADIUS = 1;

/** A point's diameter in world units: smaller as there are more of them. */
export function pointSize(count: number): number {
  return Math.min(0.045, Math.max(0.012, 0.5 / Math.cbrt(Math.max(count, 1))));
}

/** Each point's diameter: the context behind and the trials in front, each by its own count. */
export function sizes(cloud: Cloud): Float32Array {
  const ghosts = cloud.slots.reduce((count, slot) => count + Number(slot === GHOST), 0);
  const ghost = pointSize(ghosts);
  const shown = pointSize(cloud.slots.length - ghosts);
  return Float32Array.from(cloud.slots, (slot) => (slot === GHOST ? ghost : shown));
}

/** The camera distance that fits a sphere of `radius` in a view of `aspect` (width / height). */
export function fitDistance(radius: number, aspect: number, fov = FOV): number {
  const vertical = (fov * Math.PI) / 360;
  const horizontal = Math.atan(Math.tan(vertical) * aspect);
  return (radius / Math.sin(Math.min(vertical, horizontal))) * 1.05;
}

/**
 * The index of the point nearest to (x, y) on screen, within `radius` px, or null. `matrix`
 * is the camera's projection × view (column-major); points behind the camera don't count,
 * and of two at the same spot the nearer wins.
 */
export function nearestOnScreen(
  positions: Float32Array,
  matrix: ArrayLike<number>,
  width: number,
  height: number,
  x: number,
  y: number,
  radius: number,
  pickable: (index: number) => boolean = () => true,
): number | null {
  const m = matrix;
  const limit = radius * radius;
  let best: number | null = null;
  let bestDistance = limit;
  let bestDepth = Number.POSITIVE_INFINITY;
  for (let i = 0; i < positions.length / 3; i++) {
    const px = positions[i * 3] ?? 0;
    const py = positions[i * 3 + 1] ?? 0;
    const pz = positions[i * 3 + 2] ?? 0;
    const w = (m[3] ?? 0) * px + (m[7] ?? 0) * py + (m[11] ?? 0) * pz + (m[15] ?? 0);
    if (w <= 0) continue;
    const cx = ((m[0] ?? 0) * px + (m[4] ?? 0) * py + (m[8] ?? 0) * pz + (m[12] ?? 0)) / w;
    const cy = ((m[1] ?? 0) * px + (m[5] ?? 0) * py + (m[9] ?? 0) * pz + (m[13] ?? 0)) / w;
    const dx = (cx * 0.5 + 0.5) * width - x;
    const dy = (0.5 - cy * 0.5) * height - y;
    const distance = dx * dx + dy * dy;
    if (distance > limit) continue;
    // Points closer than a pixel apart are the same spot: the nearer one is on top.
    const better =
      distance < bestDistance - 1 || (Math.abs(distance - bestDistance) <= 1 && w < bestDepth);
    if (better && pickable(i)) {
      best = i;
      bestDistance = distance;
      bestDepth = w;
    }
  }
  return best;
}

/** Per-point colour and opacity (r, g, b, a) for a palette and an optional highlight. */
export function tints(cloud: Cloud, palette: Palette, highlight: number | null): Float32Array {
  const count = cloud.slots.length;
  const out = new Float32Array(count * 4);
  const alphas = cloud.slots.includes(GHOST) ? { ...ALPHA, ...ALPHA_IN_FRONT } : ALPHA;
  for (let i = 0; i < count; i++) {
    const slot = cloud.slots[i] ?? GREY;
    let colour: RGB = slot < GREY ? (palette.chart[slot] ?? palette.muted) : palette.muted;
    let alpha = slot < GREY ? COLOURED_ALPHA : (alphas[slot] ?? 0.4);
    if (highlight !== null && slot !== GHOST) {
      if (cloud.clusters[i] === highlight) {
        if (slot >= GREY) colour = palette.foreground;
        alpha = 0.95;
      } else {
        colour = palette.muted;
        alpha = FADED_ALPHA;
      }
    }
    out.set([colour[0], colour[1], colour[2], alpha], i * 4);
  }
  return out;
}

/** sRGB in 0..1 for any CSS colour, through a 1×1 canvas; black if it can't be read. */
export function cssColor(value: string): RGB {
  const hex = /^#([0-9a-f]{6})$/i.exec(value.trim());
  if (hex?.[1]) {
    const n = Number.parseInt(hex[1], 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  try {
    const context = document.createElement("canvas").getContext("2d", {
      willReadFrequently: true,
    });
    if (context) {
      context.fillStyle = "#000";
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      const [r = 0, g = 0, b = 0] = context.getImageData(0, 0, 1, 1).data;
      return [r / 255, g / 255, b / 255];
    }
  } catch {
    // jsdom and locked-down browsers: fall through.
  }
  return [0, 0, 0];
}

/** The theme's chart colours and neutrals, as `element` sees them. */
export function readPalette(element: Element): Palette {
  const style = getComputedStyle(element);
  const read = (name: string) => cssColor(style.getPropertyValue(name) || "#888888");
  return {
    chart: Array.from({ length: 8 }, (_, i) => read(`--chart-${i + 1}`)),
    muted: read("--muted-foreground"),
    foreground: read("--foreground"),
  };
}
