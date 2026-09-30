// Pure helpers for the timeline: easing, envelopes, a seeded PRNG and number
// formatting. No DOM access, so tests/util.test.js can property-test them.

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const E = {
  lin: (t) => t,
  outCubic: (t) => 1 - Math.pow(1 - t, 3),
  inCubic: (t) => t * t * t,
  outQuint: (t) => 1 - Math.pow(1 - t, 5),
  inOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  inOutQuint: (t) => (t < 0.5 ? 16 * t ** 5 : 1 - Math.pow(-2 * t + 2, 5) / 2),
  outExpo: (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  inExpo: (t) => (t <= 0 ? 0 : Math.pow(2, 10 * t - 10)),
  inOutExpo: (t) =>
    t <= 0 ? 0 : t >= 1 ? 1 : t < 0.5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2,
  outBack: (t) => {
    const c1 = 1.5, c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },
  inOutSine: (t) => -(Math.cos(Math.PI * t) - 1) / 2,
};
export const P = (t, a, b, e = E.lin) => e(clamp((t - a) / (b - a)));
// in-then-out envelope: rises over [a,b], holds, falls over [c,d]
export const env = (t, a, b, c, d, ei = E.outCubic, eo = E.inOutSine) =>
  t < c ? P(t, a, b, ei) : 1 - P(t, c, d, eo);

export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export const fmt = (n) => Math.round(n).toLocaleString("en-US");
export const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
export const mix = (a, b, t) => {
  const A = hexToRgb(a), B = hexToRgb(b);
  return `rgb(${A.map((v, i) => Math.round(lerp(v, B[i], t))).join(",")})`;
};
// YAML-style digit grouping, as policyengine-us writes parameter values (2_200)
export const fmtYaml = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "_");

// a statistic's final on-screen text; no intermediate values ever reach the screen
// currency goes in an options object so that stats.map(statText), which passes the index
// second, still reads "$"
export function statText(s, { cur = "$" } = {}) {
  const v = s.value.toFixed(s.digits ?? 0);
  if (s.kind === "billion") return `${cur}${v}<span class="u">billion</span>`;
  if (s.kind === "pct") return `${v}<span class="u" style="margin-left:0.04em">%</span>`;
  return fmt(s.value);
}

// do rects a and b come within m of each other (m < 0: overlap by more than -m)
export const hits = (a, b, m) => a.x < b.x + b.w + m && b.x < a.x + a.w + m && a.y < b.y + b.h + m && b.y < a.y + a.h + m;

// A chip sits where it was designed to unless text overlaps it there; then it takes the nearest offset
// (dx, dy) that clears every obstacle by `margin` and stays inside `inside` in every frame it shows, at
// full size if any offset allows, else at the largest of `scales` that does. frames: [{ at: (dx, dy, k)
// => the chip's drawn rect, obstacles: [rects], inside: rect }]. The design position is judged on
// `designFrames` (default: frames): the chip at rest, since its entrance slide is part of the design.
// Solved once, so frames stay history-free. Where the design position is clear (the US film) the
// result is exactly (0, 0, 1).
export function clearOffset(frames, { dxs, dys, margin, scales = [1], designFrames = frames }) {
  const ok = (fs, dx, dy, k, m) => fs.every((f) => {
    const r = f.at(dx, dy, k), b = f.inside;
    if (r.x < b.x || r.y < b.y || r.x + r.w > b.x + b.w || r.y + r.h > b.y + b.h) return false;
    return !f.obstacles.some((o) => hits(r, o, m));
  });
  if (ok(designFrames, 0, 0, 1, 0)) return { dx: 0, dy: 0, k: 1, moved: false };
  const cands = [];
  for (const dx of dxs) for (const dy of dys) cands.push([dx, dy, dx * dx + dy * dy]);
  cands.sort((p, q) => p[2] - q[2] || p[1] - q[1] || p[0] - q[0]);
  for (const k of scales) for (const [dx, dy] of cands) if (ok(frames, dx, dy, k, margin)) return { dx, dy, k, moved: true };
  return { dx: 0, dy: 0, k: 1, moved: false, stuck: true };
}
// lo, lo + by, ... up to hi
export const steps = (lo, hi, by) => Array.from({ length: Math.floor((hi - lo) / by) + 1 }, (_, i) => lo + i * by);
