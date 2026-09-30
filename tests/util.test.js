// Invariants of the timeline helpers (site/util.js). Every frame of the video is a
// function of t built from these, so their properties bound what can appear on screen.
import { describe, expect, test } from "vitest";
import fc from "fast-check";
import { clamp, lerp, E, P, env, mulberry32, fmt, mix, fmtYaml, statText, hits, clearOffset, steps } from "../site/util.js";

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

  test("statText prefixes only money, in the stated currency", () => {
    const stat = fc.record({ kind: fc.constantFrom("billion", "pct", "count"), value: fc.nat(1e6), digits: fc.constant(0) });
    fc.assert(fc.property(stat, fc.constantFrom("$", "£"), fc.nat(20), (s, cur, i) => {
      const lead = s.kind === "billion" ? cur : "";
      const withCur = statText(s, { cur });
      return withCur.startsWith(lead + String(s.value).slice(0, 1))
        && statText(s, i) === statText(s)  // an index from Array.map never becomes the currency
        && (s.kind !== "billion" || statText(s).startsWith("$"));
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

// the citation chip's placement (site/main.js placeChips): a small world of boxes, a chip that may
// shift with a "camera" from frame to frame, a coarse grid of offsets and two scales
describe("clearOffset: where a chip goes when its design position covers text", () => {
  const box = fc.record({ x: fc.integer({ min: 0, max: 180 }), y: fc.integer({ min: 0, max: 180 }),
    w: fc.integer({ min: 1, max: 60 }), h: fc.integer({ min: 1, max: 30 }) });
  const world = fc.record({
    chip: fc.record({ x: fc.integer({ min: 40, max: 120 }), y: fc.integer({ min: 40, max: 120 }),
      w: fc.integer({ min: 10, max: 50 }), h: fc.integer({ min: 6, max: 20 }) }),
    shifts: fc.array(fc.tuple(fc.integer({ min: -6, max: 6 }), fc.integer({ min: -6, max: 6 })), { minLength: 1, maxLength: 3 }),
    obstacles: fc.array(box, { maxLength: 8 }),
    margin: fc.integer({ min: 0, max: 4 }),
    // the frame the chip must stay in; tight enough that it often decides where the chip can go
    inside: fc.record({ x: fc.integer({ min: 0, max: 60 }), y: fc.integer({ min: 0, max: 60 }),
      w: fc.integer({ min: 60, max: 200 }), h: fc.integer({ min: 40, max: 200 }) }),
  });
  const GRID = { dxs: steps(-60, 60, 6), dys: steps(-60, 60, 6), scales: [1, 0.8] };
  const framesOf = ({ chip, shifts, obstacles, inside }) => shifts.map(([sx, sy]) => ({
    inside,
    obstacles: obstacles.map((o) => ({ ...o, x: o.x + sx, y: o.y + sy })),
    at: (dx, dy, k) => ({ x: chip.x + sx + dx + ((1 - k) * chip.w) / 2, y: chip.y + sy + dy + ((1 - k) * chip.h) / 2, w: k * chip.w, h: k * chip.h }),
  }));
  const clear = (frames, dx, dy, k, m) => frames.every((f) => {
    const r = f.at(dx, dy, k);
    return r.x >= f.inside.x && r.y >= f.inside.y && r.x + r.w <= f.inside.x + f.inside.w && r.y + r.h <= f.inside.y + f.inside.h
      && f.obstacles.every((o) => !hits(r, o, m));
  });

  test("keeps the design position exactly whenever nothing overlaps it there", () => {
    fc.assert(fc.property(world, (w) => {
      const frames = framesOf(w);
      fc.pre(clear(frames, 0, 0, 1, 0));
      const r = clearOffset(frames, { ...GRID, margin: w.margin });
      return r.dx === 0 && r.dy === 0 && r.k === 1 && !r.moved;
    }));
  });

  test("a moved chip clears every obstacle by the margin and stays inside, in every frame", () => {
    fc.assert(fc.property(world, (w) => {
      const frames = framesOf(w), r = clearOffset(frames, { ...GRID, margin: w.margin });
      return !r.moved || clear(frames, r.dx, r.dy, r.k, w.margin);
    }));
  });

  test("the move is the shortest the grid allows, at the largest scale that allows one", () => {
    fc.assert(fc.property(world, (w) => {
      const frames = framesOf(w), r = clearOffset(frames, { ...GRID, margin: w.margin });
      fc.pre(r.moved);
      const d = r.dx * r.dx + r.dy * r.dy;
      for (const k of GRID.scales) {
        for (const dx of GRID.dxs) for (const dy of GRID.dys) {
          const ok = clear(frames, dx, dy, k, w.margin);
          if (k > r.k && ok) return false;                          // a larger size fitted somewhere
          if (k === r.k && ok && dx * dx + dy * dy < d) return false; // a shorter move fitted
        }
      }
      return true;
    }));
  });

  // crowded worlds too, so that both sides of "stuck" come up
  const crowded = world.chain((w) => fc.array(fc.record({ x: fc.integer({ min: 0, max: 200 }), y: fc.integer({ min: 0, max: 200 }),
    w: fc.integer({ min: 20, max: 120 }), h: fc.integer({ min: 10, max: 60 }) }), { minLength: 0, maxLength: 30 })
    .map((extra) => ({ ...w, obstacles: [...w.obstacles, ...extra] })));

  test("reports stuck exactly when neither the design position nor any offset at any scale clears", () => {
    fc.assert(fc.property(crowded, (w) => {
      const frames = framesOf(w), r = clearOffset(frames, { ...GRID, margin: w.margin });
      const none = !clear(frames, 0, 0, 1, 0)
        && GRID.scales.every((k) => GRID.dxs.every((dx) => GRID.dys.every((dy) => !clear(frames, dx, dy, k, w.margin))));
      return !!r.stuck === none && (!r.stuck || (r.dx === 0 && r.dy === 0 && r.k === 1));
    }), { numRuns: 300 });
  });

  test("the design position is judged on designFrames alone; a move must clear every frame", () => {
    fc.assert(fc.property(world, fc.integer({ min: 1, max: 12 }), (w, slide) => {
      const rest = framesOf(w);
      // the same frames with the chip slid `slide` px lower, as it is while fading in and out
      const moving = rest.map((f) => ({ ...f, at: (dx, dy, k) => { const r = f.at(dx, dy, k); return { ...r, y: r.y + slide }; } }));
      const r = clearOffset(moving, { ...GRID, margin: w.margin, designFrames: rest });
      if (clear(rest, 0, 0, 1, 0)) return r.dx === 0 && r.dy === 0 && r.k === 1 && !r.moved;
      return !r.moved || clear(moving, r.dx, r.dy, r.k, w.margin);
    }));
  });

  test("hits is symmetric and grows with the margin", () => {
    fc.assert(fc.property(box, box, fc.integer({ min: -5, max: 5 }), (a, b, m) =>
      hits(a, b, m) === hits(b, a, m) && (!hits(a, b, m) || hits(a, b, m + 1))));
  });

  test("steps runs from lo by `by` and stops at or before hi", () => {
    fc.assert(fc.property(fc.integer({ min: -500, max: 500 }), fc.integer({ min: 0, max: 900 }), fc.integer({ min: 1, max: 50 }),
      (lo, span, by) => {
        const s = steps(lo, lo + span, by);
        return s[0] === lo && s.every((v, i) => i === 0 || v - s[i - 1] === by) && s.at(-1) <= lo + span && s.at(-1) + by > lo + span;
      }));
  });
});

