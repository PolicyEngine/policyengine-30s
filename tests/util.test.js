// Invariants of the timeline helpers (site/util.js). Every frame of the video is a
// function of t built from these, so their properties bound what can appear on screen.
import { describe, expect, test } from "vitest";
import fc from "fast-check";
import { clamp, lerp, E, P, env, mulberry32, fmt, mix, fmtYaml, statText } from "../site/util.js";

const MONOTONE = ["lin", "outCubic", "inCubic", "outQuint", "inOutCubic", "inOutQuint", "outExpo", "inExpo", "inOutExpo", "inOutSine"];
const unit = fc.double({ min: 0, max: 1, noNaN: true });
const time = fc.double({ min: -100, max: 100, noNaN: true });
const span = fc.tuple(time, fc.double({ min: 1e-3, max: 50, noNaN: true })).map(([a, w]) => [a, a + w]);
const EPS = 1e-12;

describe("easing curves", () => {
  test.each(Object.keys(E))("%s maps 0 to 0 and 1 to 1", (name) => {
    expect(E[name](0)).toBeCloseTo(0, 12);
    expect(E[name](1)).toBeCloseTo(1, 12);
  });

  test.each(MONOTONE)("%s stays in [0, 1] and never decreases", (name) => {
    fc.assert(fc.property(unit, unit, (x, y) => {
      const [lo, hi] = x <= y ? [x, y] : [y, x];
      const a = E[name](lo), b = E[name](hi);
      return a >= -EPS && b <= 1 + EPS && a <= b + EPS;
    }));
  });

  test("outBack overshoots above 1 (intended: the settle-back pop)", () => {
    expect(Math.max(...Array.from({ length: 101 }, (_, i) => E.outBack(i / 100)))).toBeGreaterThan(1);
  });
});

describe("P: progress through an interval", () => {
  test("is 0 before the interval, 1 after it, in [0, 1] everywhere", () => {
    fc.assert(fc.property(time, span, fc.constantFrom(...MONOTONE), (t, [a, b], name) => {
      const p = P(t, a, b, E[name]);
      if (t <= a) return Math.abs(p) < EPS;
      if (t >= b) return Math.abs(p - 1) < EPS;
      return p >= -EPS && p <= 1 + EPS;
    }));
  });

  test("never decreases as time moves forward", () => {
    fc.assert(fc.property(time, time, span, fc.constantFrom(...MONOTONE), (t1, t2, [a, b], name) => {
      const [lo, hi] = t1 <= t2 ? [t1, t2] : [t2, t1];
      return P(lo, a, b, E[name]) <= P(hi, a, b, E[name]) + EPS;
    }));
  });
});

describe("env: rise, hold, fall", () => {
  const phases = fc.array(fc.double({ min: 1e-3, max: 10, noNaN: true }), { minLength: 4, maxLength: 4 })
    .chain((w) => time.map((a) => [a, a + w[0], a + w[0] + w[1], a + w[0] + w[1] + w[2]]));
  test("is 0 before it starts, 1 while it holds, 0 after it ends, in [0, 1] always", () => {
    fc.assert(fc.property(phases, time, ([a, b, c, d], t) => {
      const v = env(t, a, b, c, d);
      if (t <= a) return Math.abs(v) < EPS;
      if (t >= b && t < c) return Math.abs(v - 1) < EPS;
      if (t >= d) return Math.abs(v) < EPS;
      return v >= -EPS && v <= 1 + EPS;
    }));
  });
});

describe("mulberry32: the only randomness in the film", () => {
  test("the same seed gives the same sequence, always in [0, 1)", () => {
    fc.assert(fc.property(fc.integer(), (seed) => {
      const a = mulberry32(seed), b = mulberry32(seed);
      for (let i = 0; i < 50; i++) {
        const x = a();
        if (x !== b() || x < 0 || x >= 1) return false;
      }
      return true;
    }));
  });
});

describe("number formatting", () => {
  const amount = fc.double({ min: -1e12, max: 1e12, noNaN: true });
  test("fmt round-trips to the rounded value with comma grouping", () => {
    fc.assert(fc.property(amount, (n) => {
      const s = fmt(n);
      const back = Number(s.replace(/,/g, ""));
      return back === Math.round(n) + 0 && /^-?\d{1,3}(,\d{3})*$/.test(s);
    }));
  });

  test("fmtYaml groups digits the way policyengine-us parameter files do", () => {
    fc.assert(fc.property(fc.nat(10_000_000), (n) => {
      const s = fmtYaml(n);
      return Number(s.replace(/_/g, "")) === n && /^\d{1,3}(_\d{3})*$/.test(s);
    }));
    expect(fmtYaml(2200)).toBe("2_200");
  });

  test("statText shows exactly the stored value at the stated precision", () => {
    const stat = fc.record({
      kind: fc.constantFrom("billion", "pct", "count"),
      value: fc.double({ min: 0, max: 1e7, noNaN: true }),
      digits: fc.integer({ min: 0, max: 2 }),
    });
    fc.assert(fc.property(stat, (s) => {
      const shown = statText(s).replace(/<[^>]+>[^<]*<\/span>/g, "").replace(/[$,]/g, "");
      const expected = s.kind === "count" ? Math.round(s.value) : Number(s.value.toFixed(s.digits));
      return Number(shown) === expected;
    }));
  });
});

describe("colour mixing", () => {
  const hex = fc.tuple(fc.nat(255), fc.nat(255), fc.nat(255)).map((c) => "#" + c.map((v) => v.toString(16).padStart(2, "0")).join(""));
  test("hits both endpoints and keeps every channel between them", () => {
    fc.assert(fc.property(hex, hex, unit, (a, b, t) => {
      const ch = (s) => s.match(/\d+/g).map(Number);
      const A = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
      const B = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
      const M = ch(mix(a, b, t));
      return ch(mix(a, b, 0)).every((v, i) => v === A[i]) && ch(mix(a, b, 1)).every((v, i) => v === B[i])
        && M.every((v, i) => v >= Math.min(A[i], B[i]) && v <= Math.max(A[i], B[i]));
    }));
  });
});

test("clamp and lerp", () => {
  fc.assert(fc.property(time, time, unit, (a, b, t) => {
    const x = lerp(a, b, t);
    return x >= Math.min(a, b) - 1e-9 && x <= Math.max(a, b) + 1e-9 && clamp(x, 0, 1) >= 0 && clamp(x, 0, 1) <= 1;
  }));
});

// Golden values: the properties above hold for many curves, so pin the ones the film uses.
// The dot layout and every light-up time come from mulberry32(20260924).
describe("golden values", () => {
  test("mulberry32(20260924) starts the sequence the render used", () => {
    const r = mulberry32(20260924);
    expect([r(), r(), r()]).toEqual([0.5380521984770894, 0.6727424410637468, 0.8195708128623664]);
  });

  test("easing curves at 1/4, 1/2, 3/4", () => {
    const golden = {"lin":[0.25,0.5,0.75],"outCubic":[0.578125,0.875,0.984375],"inCubic":[0.015625,0.125,0.421875],"outQuint":[0.7626953125,0.96875,0.9990234375],"inOutCubic":[0.0625,0.5,0.9375],"inOutQuint":[0.015625,0.5,0.984375],"outExpo":[0.8232233047033631,0.96875,0.99447572827198],"inExpo":[0.005524271728019903,0.03125,0.1767766952966369],"inOutExpo":[0.015625,0.5,0.984375],"outBack":[0.7890625,1.0625,1.0546875],"inOutSine":[0.1464466094067262,0.49999999999999994,0.8535533905932737]};
    // Math.pow and Math.cos may differ in the last bit between platforms (seen: macOS vs Linux
    // for inExpo), so these compare to 12 decimal places; the integer-only PRNG above is exact everywhere
    for (const [k, v] of Object.entries(golden)) [0.25, 0.5, 0.75].map(E[k]).forEach((x, i) => expect(x).toBeCloseTo(v[i], 12));
    expect(Object.keys(E).sort()).toEqual(Object.keys(golden).sort());
  });

  test("the three statistics render exactly as published", async () => {
    const { readFileSync } = await import("node:fs");
    const video = JSON.parse(readFileSync(new URL("../data/video.json", import.meta.url)));
    expect(video.nation.stats.map(statText)).toEqual([
      '$31<span class="u">billion</span>',
      '19.2<span class="u" style="margin-left:0.04em">%</span>',
      "189,300",
    ]);
  });
});
