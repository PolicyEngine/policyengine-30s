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
export function statText(s) {
  const v = s.value.toFixed(s.digits ?? 0);
  if (s.kind === "billion") return `$${v}<span class="u">billion</span>`;
  if (s.kind === "pct") return `${v}<span class="u" style="margin-left:0.04em">%</span>`;
  return fmt(s.value);
}
