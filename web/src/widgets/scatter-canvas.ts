/**
 * The dashboard's 2-D landscape on a canvas: thousands of dots as SVG elements took Recharts a
 * long task of hundreds of milliseconds on a cold load, and a canvas draws them in a few. The
 * grid and the dots are drawn here; the axes are the data's extent, as Recharts had them, and
 * the dot under the pointer is found on the CPU. Tests replace `LandscapeCanvas` (jsdom has no
 * canvas) and keep the pure functions.
 */
import {
  cssColor,
  FAINT,
  GHOST,
  GREY,
  type Palette,
  type RGB,
  readPalette,
} from "./scatter3d-points";

/** Dots in drawing order, later on top, each in a colour slot as in the 3-D landscape. */
export type Dots = { xs: Float64Array; ys: Float64Array; slots: Uint8Array };

export type Colors = Palette & { grid: RGB };

/** Where the dots go on a canvas of `width` × `height` CSS px. */
export type Frame = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
};

/** A dot under the pointer: its index and where it is on the canvas. */
export type Hit = { index: number; x: number; y: number };

/** Recharts' margins (top 8, right 8), and room for half a dot at the left and bottom edges. */
const MARGIN = { top: 8, right: 8, bottom: 5, left: 5 };
/** The size Recharts drew them: its default symbol, a circle of 64 px² (about 9 px across). */
export const DOT_RADIUS = Math.sqrt(64 / Math.PI);
/** A dot this close (px) to the pointer counts as under it. */
export const PICK_RADIUS = 8;
const TAU = Math.PI * 2;

const FILL_ALPHA: Record<number, number> = { [GREY]: 0.3, [FAINT]: 0.15, [GHOST]: 0.1 };
const COLOURED_ALPHA = 0.75;

export function frameFor(dots: Dots, width: number, height: number): Frame {
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (let i = 0; i < dots.xs.length; i++) {
    const x = dots.xs[i] ?? 0;
    const y = dots.ys[i] ?? 0;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  if (minX > maxX) [minX, maxX, minY, maxY] = [0, 1, 0, 1];
  return {
    minX,
    maxX,
    minY,
    maxY,
    left: MARGIN.left,
    right: Math.max(MARGIN.left, width - MARGIN.right),
    top: MARGIN.top,
    bottom: Math.max(MARGIN.top, height - MARGIN.bottom),
  };
}

/** A data x on screen; the middle if every dot has the same x. */
export function screenX(frame: Frame, x: number): number {
  const span = frame.maxX - frame.minX;
  if (span <= 0) return (frame.left + frame.right) / 2;
  return frame.left + ((x - frame.minX) / span) * (frame.right - frame.left);
}

/** A data y on screen, larger y higher up. */
export function screenY(frame: Frame, y: number): number {
  const span = frame.maxY - frame.minY;
  if (span <= 0) return (frame.top + frame.bottom) / 2;
  return frame.bottom - ((y - frame.minY) / span) * (frame.bottom - frame.top);
}

/**
 * Where the grid lines go: Recharts' ticks for a number axis whose domain is the data's
 * extent (`getTickValuesFixedDomain`, 5 ticks), so the grid is where it was: from the minimum
 * in a rounded step while below the maximum, then the maximum.
 */
export function gridTicks(min: number, max: number, count = 5): number[] {
  if (!(Number.isFinite(min) && Number.isFinite(max))) return [];
  if (min === max) return [min];
  const step = roundStep((max - min) / (Math.max(count, 2) - 1));
  const ticks: number[] = [];
  for (let i = 0; min + i * step < max; i++) ticks.push(min + i * step);
  ticks.push(max);
  return ticks;
}

/** Recharts' `getFormatStep`: up to the next 0.1 of a one-digit step, or 0.05 of a power of ten. */
function roundStep(rough: number): number {
  const digits = Math.floor(Math.log10(Math.abs(rough))) + 1;
  const power = 10 ** digits;
  const scale = digits !== 1 ? 0.05 : 0.1;
  return Math.ceil(rough / power / scale - 1e-9) * scale * power;
}

/**
 * The dot under (x, y): the one drawn last (on top) of those the pointer is on, or else the
 * nearest within `radius` px, or null. The context behind a window (GHOST) isn't pickable.
 */
export function nearestDot(
  dots: Dots,
  frame: Frame,
  x: number,
  y: number,
  radius = PICK_RADIUS,
): Hit | null {
  const on = DOT_RADIUS * DOT_RADIUS;
  let top: number | null = null;
  let near: number | null = null;
  let nearDistance = radius * radius;
  for (let i = 0; i < dots.xs.length; i++) {
    if (dots.slots[i] === GHOST) continue;
    const dx = screenX(frame, dots.xs[i] ?? 0) - x;
    const dy = screenY(frame, dots.ys[i] ?? 0) - y;
    const distance = dx * dx + dy * dy;
    if (distance <= on) top = i;
    else if (top === null && distance <= nearDistance) {
      near = i;
      nearDistance = distance;
    }
  }
  const index = top ?? near;
  if (index === null) return null;
  return {
    index,
    x: screenX(frame, dots.xs[index] ?? 0),
    y: screenY(frame, dots.ys[index] ?? 0),
  };
}

/** The theme's chart colours, neutrals and grid colour, as `element` sees them. */
export function readColors(element: Element): Colors {
  const grid = getComputedStyle(element).getPropertyValue("--chart-grid");
  return { ...readPalette(element), grid: cssColor(grid || "#e6e6e3") };
}

const rgb = ([r, g, b]: RGB) =>
  `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;

/** Draws the grid and the dots on a canvas, at the screen's pixel ratio, whenever one changes. */
export class LandscapeCanvas {
  private readonly canvas: HTMLCanvasElement;
  private readonly context: CanvasRenderingContext2D | null;
  private dots: Dots = { xs: new Float64Array(), ys: new Float64Array(), slots: new Uint8Array() };
  private colors: Colors | null = null;
  private frame: Frame = frameFor(this.dots, 0, 0);
  private width = 0;
  private height = 0;
  private ratio = 1;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
  }

  setDots(dots: Dots): void {
    this.dots = dots;
    this.frame = frameFor(dots, this.width, this.height);
    this.draw();
  }

  setColors(colors: Colors): void {
    this.colors = colors;
    this.draw();
  }

  resize(width: number, height: number): void {
    const ratio = window.devicePixelRatio || 1;
    if (width === this.width && height === this.height && ratio === this.ratio) return;
    this.width = width;
    this.height = height;
    this.ratio = ratio;
    this.canvas.width = Math.round(width * ratio);
    this.canvas.height = Math.round(height * ratio);
    this.frame = frameFor(this.dots, width, height);
    this.draw(); // now, not next frame: resizing cleared the canvas
  }

  pick(x: number, y: number): Hit | null {
    return nearestDot(this.dots, this.frame, x, y);
  }

  private draw(): void {
    const c = this.context;
    const colors = this.colors;
    if (!c || !colors || this.width <= 0 || this.height <= 0) return;
    const { frame, ratio } = this;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.setTransform(ratio, 0, 0, ratio, 0, 0);

    // The grid: 1 px dashed lines, on whole device pixels.
    const crisp = (v: number) => (Math.round(v * ratio) + (ratio % 2 === 1 ? 0.5 : 0)) / ratio;
    c.globalAlpha = 1;
    c.strokeStyle = rgb(colors.grid);
    c.lineWidth = 1;
    c.setLineDash([3, 3]);
    c.beginPath();
    for (const tick of gridTicks(frame.minX, frame.maxX)) {
      const x = crisp(screenX(frame, tick));
      c.moveTo(x, frame.top);
      c.lineTo(x, frame.bottom);
    }
    for (const tick of gridTicks(frame.minY, frame.maxY)) {
      const y = crisp(screenY(frame, tick));
      c.moveTo(frame.left, y);
      c.lineTo(frame.right, y);
    }
    c.stroke();
    c.setLineDash([]);

    // The dots, each filled on its own so overlaps darken as they did in SVG; coloured ones
    // get a thin outline in full colour.
    const { xs, ys, slots } = this.dots;
    const muted = rgb(colors.muted);
    const chart = colors.chart.map(rgb);
    c.lineWidth = 0.5;
    let current = -1;
    let alpha = 1;
    let outlined = false;
    for (let i = 0; i < slots.length; i++) {
      const slot = slots[i] ?? GREY;
      if (slot !== current) {
        current = slot;
        outlined = slot < GREY;
        const colour = outlined ? (chart[slot] ?? muted) : muted;
        c.fillStyle = colour;
        c.strokeStyle = colour;
        alpha = outlined ? COLOURED_ALPHA : (FILL_ALPHA[slot] ?? 0.3);
        c.globalAlpha = alpha;
      }
      c.beginPath();
      c.arc(screenX(frame, xs[i] ?? 0), screenY(frame, ys[i] ?? 0), DOT_RADIUS, 0, TAU);
      c.fill();
      if (outlined) {
        c.globalAlpha = 1;
        c.stroke();
        c.globalAlpha = alpha;
      }
    }
    c.globalAlpha = 1;
  }
}
