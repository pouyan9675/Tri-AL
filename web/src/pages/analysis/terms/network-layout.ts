/**
 * Where the network's nodes go: a force-directed layout (Fruchterman and Reingold) with the
 * term pinned in the middle. Nodes push each other apart, edges pull the terms that share
 * trials together (harder the more they share), and a pull toward the middle keeps terms
 * without edges from drifting off. The term in the middle pushes harder, so it keeps room
 * around it. It starts from a circle ordered by group and cools over a fixed number of
 * steps, so the same network always lands the same way. Positions are in the unit disk.
 */

export type LayoutNode = { group: number; center: boolean };
export type LayoutEdge = { source: number; target: number; jaccard: number };
export type Position = { x: number; y: number };

const ITERATIONS = 300;
const CENTER_PULL = 0.3;
/** The term in the middle pushes this many times harder, so it keeps room around it. */
const CENTER_PUSH = 4;

export function layoutNetwork(nodes: LayoutNode[], edges: LayoutEdge[]): Position[] {
  const n = nodes.length;
  if (n === 0) return [];
  const others = nodes
    .map((node, index) => ({ node, index }))
    .filter(({ node }) => !node.center)
    .sort((a, b) => a.node.group - b.node.group || a.index - b.index);
  const xs = new Float64Array(n);
  const ys = new Float64Array(n);
  others.forEach(({ index }, i) => {
    const angle = (2 * Math.PI * i) / Math.max(1, others.length) - Math.PI / 2;
    xs[index] = 0.7 * Math.cos(angle);
    ys[index] = 0.7 * Math.sin(angle);
  });
  const k = 2.6 / Math.sqrt(n);
  const strongest = Math.max(1e-9, ...edges.map((edge) => edge.jaccard));
  const pinned = nodes.map((node) => node.center);
  const dx = new Float64Array(n);
  const dy = new Float64Array(n);
  for (let step = 0; step < ITERATIONS; step++) {
    const temperature = 0.12 * (1 - step / ITERATIONS) + 0.002;
    dx.fill(0);
    dy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ex = (xs[i] ?? 0) - (xs[j] ?? 0);
        let ey = (ys[i] ?? 0) - (ys[j] ?? 0);
        let distance = Math.hypot(ex, ey);
        if (distance < 1e-6) {
          // Two nodes on top of each other: nudge them apart the same way every time.
          ex = 1e-3 * (i - j);
          ey = 1e-3;
          distance = Math.hypot(ex, ey);
        }
        const push = ((pinned[i] || pinned[j] ? CENTER_PUSH : 1) * k * k) / distance;
        const fx = (ex / distance) * push;
        const fy = (ey / distance) * push;
        dx[i] = (dx[i] ?? 0) + fx;
        dy[i] = (dy[i] ?? 0) + fy;
        dx[j] = (dx[j] ?? 0) - fx;
        dy[j] = (dy[j] ?? 0) - fy;
      }
    }
    for (const edge of edges) {
      const { source: i, target: j } = edge;
      const ex = (xs[i] ?? 0) - (xs[j] ?? 0);
      const ey = (ys[i] ?? 0) - (ys[j] ?? 0);
      const distance = Math.hypot(ex, ey);
      if (distance < 1e-9) continue;
      const pull = ((distance * distance) / k) * (0.3 + edge.jaccard / strongest);
      const fx = (ex / distance) * pull;
      const fy = (ey / distance) * pull;
      dx[i] = (dx[i] ?? 0) - fx;
      dy[i] = (dy[i] ?? 0) - fy;
      dx[j] = (dx[j] ?? 0) + fx;
      dy[j] = (dy[j] ?? 0) + fy;
    }
    for (let i = 0; i < n; i++) {
      if (pinned[i]) continue;
      const x = xs[i] ?? 0;
      const y = ys[i] ?? 0;
      const distance = Math.hypot(x, y);
      if (distance > 1e-9) {
        const pull = ((distance * distance) / k) * CENTER_PULL;
        dx[i] = (dx[i] ?? 0) - (x / distance) * pull;
        dy[i] = (dy[i] ?? 0) - (y / distance) * pull;
      }
      const move = Math.hypot(dx[i] ?? 0, dy[i] ?? 0);
      if (move > 1e-12) {
        const limited = Math.min(move, temperature);
        const nx = x + ((dx[i] ?? 0) / move) * limited;
        const ny = y + ((dy[i] ?? 0) / move) * limited;
        const reach = Math.hypot(nx, ny);
        // Kept inside the unit disk.
        xs[i] = reach > 1 ? nx / reach : nx;
        ys[i] = reach > 1 ? ny / reach : ny;
      }
    }
  }
  return scaled(xs, ys, pinned);
}

/** Scaled so the furthest node is on the edge of the disk, the pinned middle staying put. */
function scaled(xs: Float64Array, ys: Float64Array, pinned: boolean[]): Position[] {
  let reach = 0;
  for (let i = 0; i < xs.length; i++) {
    reach = Math.max(reach, Math.hypot(xs[i] ?? 0, ys[i] ?? 0));
  }
  const scale = reach > 1e-9 ? 1 / reach : 1;
  return Array.from(xs, (x, i) =>
    pinned[i] ? { x: 0, y: 0 } : { x: x * scale, y: (ys[i] ?? 0) * scale },
  );
}

export type Label = {
  x: number;
  y: number;
  /** The node's radius, so the label starts clear of it. */
  r: number;
  width: number;
  height: number;
  /** Labels are placed in this order: the most important first. */
  priority: number;
  /** The side to try first. */
  prefer: "left" | "right";
};

type Box = { left: number; right: number; top: number; bottom: number };

const overlaps = (a: Box, b: Box) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/**
 * Which side of its node each label goes, or null where both sides would cover a label
 * already placed (or a node): the label then shows on hover only. Greedy, by priority.
 */
export function placeLabels(labels: Label[], gap = 4): ("left" | "right" | null)[] {
  const nodes: Box[] = labels.map(({ x, y, r }) => ({
    left: x - r,
    right: x + r,
    top: y - r,
    bottom: y + r,
  }));
  const placed: Box[] = [];
  const sides: ("left" | "right" | null)[] = labels.map(() => null);
  const order = labels
    .map((_, i) => i)
    .sort((a, b) => {
      const pa = labels[a]?.priority ?? 0;
      const pb = labels[b]?.priority ?? 0;
      return pb - pa || a - b;
    });
  for (const i of order) {
    const label = labels[i];
    if (!label) continue;
    const { x, y, r, width, height, prefer } = label;
    const options =
      prefer === "right" ? (["right", "left"] as const) : (["left", "right"] as const);
    for (const side of options) {
      const left = side === "right" ? x + r + gap : x - r - gap - width;
      const box = { left, right: left + width, top: y - height / 2, bottom: y + height / 2 };
      const clear =
        !placed.some((other) => overlaps(box, other)) &&
        !nodes.some((node, j) => j !== i && overlaps(box, node));
      if (clear) {
        sides[i] = side;
        placed.push(box);
        break;
      }
    }
  }
  return sides;
}
