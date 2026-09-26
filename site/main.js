// PolicyEngine in 30 seconds — deterministic timeline.
// window.renderAt(t) draws the frame at time t (seconds). Every number shown
// comes from /data/video.json, built by tools/build_video_data.py from the
// PolicyEngine runs in data/. If video.json is missing, the page falls back to
// MOCK_VIDEO and paints a striped MOCK DATA banner on every frame.

import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import statesTopo from "us-atlas/states-10m.json";
import { clamp, lerp, E, P, env, mulberry32, fmt, mix, fmtYaml, statText } from "./util.js";

const Q = new URLSearchParams(location.search);
const W = +(Q.get("w") || 1920);
const H = +(Q.get("h") || 1080);
const VERT = H > W;
const DPR = window.devicePixelRatio || 1;
const DUR = 30;

const el = (tag, cls, parent, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  if (parent) parent.appendChild(e);
  return e;
};
const css = (e, o) => Object.assign(e.style, o);

// ------------------------------------------------------------------ timeline
// 120 BPM: one beat = 0.5 s, one bar = 2 s. Scene cuts land on bar lines.
const T = {
  pourA: -0.6, pourB: 1.4,          // pre-rolled: frame 0 already shows statute
  quoteIn: 0.2, qStag: 0.1, quoteOut: 2.7,
  lawFocus: 3.45, zoomAmt: 3.5,
  flyStart: 4.0, flyEnd: 4.85,
  codeIn: 4.1,
  cap1In: 4.45,
  refIn: 5.3,
  cap2In: 6.3,
  reformIn: 6.75, reformVal: 7.25,
  famIn: 8.5,
  chartIn: 8.8,
  curveA: 9.1, curveB: 10.9,        // the curve draws across earnings, left to right
  riseA: 11.0, riseB: 11.95,        // riser over beats 3-4, drums and bass out
  line1: 11.0, line2: 12.0,         // "+$1,600 from …" and its hit on the downbeat, never on beat 4
  noteIn: 12.15,
  famOut: 13.75,
  zoomA: 14.0, zoomB: 16.3,
  rippleA: 14.9, rippleB: 16.6,
  stat1: 16.5, stat2: 17.0, stat3: 17.5,
  hexA: 20.0, hexB: 21.3,
  hexFill: 21.0,
  logoA: 25.0, logoB: 26.0,
  tag: 26.35, url: 26.9,
};

// ---------------------------------------------------------------- mock data
// MOCK_VIDEO exists only so the timeline can be previewed before the real
// PolicyEngine outputs land. Any frame drawn from it carries the banner.
const MOCK_VIDEO = {
  mock: true,
  quote: { text: "…the laws be so voluminous that they cannot be read…", attr: "Federalist No. 62 · 1788" },
  statute: { wall: "MOCK STATUTE TEXT ".repeat(900), h2: "MOCK (h)(2) paragraph with $2,200 in it.", amount: "$2,200", cite: "26 U.S.C. § 24(h)(2)" },
  code: null,
  reform: { label: "Child Tax Credit amount", path: "gov.irs.credits.ctc.amount.base[0].amount", from: 2200, to: 3000, year: 2026 },
  household: {
    who: "MOCK household",
    curve: { points: [[0, 0], [60000, 0], [120000, 0]], xMax: 120000, pin: [60000, 0], lines: ["MOCK", "MOCK"], note: "MOCK" },
    gain: 0,
  },
  nation: {
    stats: [
      { num: "$00", unit: "billion", what: "MOCK federal cost" },
      { num: "00%", what: "MOCK share gaining" },
    ],
    perDot: 11000,
  },
  districts: null,
};

// ------------------------------------------------------------------- state
let V = null;           // video data
let wordCount;
let stage, wallCam, wall, amtEl, amtBox, quote, quoteWords, quoteAttr, lawChip;
let code, codeLines, codeVal, codeRefLine, token, tokA, tokB;
let cap1, cap2, capNation, capDist, reform, reformLines, reformVal;
let famWrap, famSvg, famDesc, chart, chartSvg, curvePath, playhead, pinEl, lineEls, noteEl, reformChip;
let statEls, legendDots;
let logoImg, tagEl, urlEl, mockBanner, srcNation, srcDeciles;
let cv, ctx, grainCv, grainCtx;
let M = {};             // cached measurements
let dots = [];          // population sample
let map = {};           // projection + geometry
let bars = [];          // income-decile bars
let barLbl = [], barAx = [], axEnds;
let logoPts = [];
let EVENTS = [];

// ------------------------------------------------------------------ layout
function layout() {
  // All positions in stage px. Portrait variant rearranges the same pieces.
  if (!VERT) {
    return {
      margin: 120,
      code: { x: W - 120 - 960, y: 150, w: 960 },
      cap: { x: 120, y: 230, w: 680, size: 78 },
      reform: { x: 120, y: 600, w: 680 },
      fam: { x: 130, y: 240, w: 560, h: 300 },
      famDesc: { x: 120, y: 580, w: 600 },
      chart3: { x: 800, y: 170, w: 980, h: 440 },
      lines3: { x: 800, y: 680, size: 60 },
      gain: { x: 760, y: 745, size: 124 },
      capTop: { x: 120, y: 96, w: 1200, size: 64 },
      mapBox: [[660, 290], [1800, 960]],
      chart: [[330, 330], [1590, 880]],
      stats: { x: 120, y: 330, gap: 200 },
      legend: { x: 120, y: 184 },
      logo: { cx: W / 2, cy: H / 2 - 70, w: 1000 },
    };
  }
  return {
    margin: 72,
    code: { x: 60, y: 830, w: 960 },
    cap: { x: 72, y: 250, w: 936, size: 80 },
    reform: { x: 72, y: 560, w: 936 },
    fam: { x: 260, y: 280, w: 560, h: 300 },
    famDesc: { x: 72, y: 640, w: 940 },
    chart3: { x: 90, y: 850, w: 880, h: 400 },
    lines3: { x: 72, y: 1330, size: 58 },
    gain: { x: 72, y: 1380, size: 116 },
    capTop: { x: 72, y: 290, w: 936, size: 62 },
    mapBox: [[72, 560], [1008, 1160]],
    chart: [[80, 640], [1000, 1380]],
    stats: { x: 72, y: 1230, gap: 210 },
    legend: { x: 72, y: 440 },
    logo: { cx: W / 2, cy: H / 2 - 110, w: 900 },
  };
}
let L;

// ------------------------------------------------------------------- build
function buildCaption(tokens, cls, parent) {
  // tokens: [[text, className?], ...] split into word spans for staggered entry
  const c = el("div", "caption " + (cls || ""), parent);
  for (const [raw, k] of tokens) {
    const text = raw.replace(/^\n/, () => { el("br", "", c); return ""; });
    for (const w of text.split(/(?<= )/)) {
      const s = el("span", "w" + (k ? " " + k : ""), c);
      s.textContent = w;
    }
  }
  return c;
}

function splitWall(text, ncol) {
  const words = text.split(/(\s+)/);
  const target = text.length / ncol;
  const cols = [];
  let cur = "", n = 0;
  for (const w of words) {
    cur += w; n += w.length;
    if (n >= target && cols.length < ncol - 1 && /\n/.test(w)) {
      cols.push(cur); cur = ""; n = 0;
    }
  }
  cols.push(cur);
  return cols;
}

function build() {
  L = layout();
  stage = document.getElementById("stage");
  if (VERT) stage.classList.add("vert");
  document.documentElement.style.setProperty("--W", W + "px");
  document.documentElement.style.setProperty("--H", H + "px");

  // --- canvas layers
  cv = el("canvas", "layer", stage);
  cv.width = W * DPR; cv.height = H * DPR;
  ctx = cv.getContext("2d");

  // --- scene 1: wall of statute
  wallCam = el("div", "", stage); wallCam.id = "wallCam";
  wall = el("div", "", wallCam); wall.id = "wall";
  const st = V.statute;
  const ncol = VERT ? 3 : 5;
  const full = st.wall;
  const h2i = st.wall_h2_offset != null ? st.wall_h2_offset : full.indexOf(st.h2);
  const cols = splitWall(full, ncol);
  let off = 0;
  for (const ctext of cols) {
    const col = el("div", "col", wall);
    const a = off, b = off + ctext.length;
    if (h2i >= a && h2i < b) {
      const pre = ctext.slice(0, h2i - a);
      const h2 = full.slice(h2i, h2i + st.h2.length);
      const post = full.slice(h2i + st.h2.length, b);
      col.appendChild(document.createTextNode(pre));
      const h2s = el("span", "h2", col);
      const ai = h2.indexOf(st.amount);
      h2s.appendChild(document.createTextNode(h2.slice(0, ai)));
      amtEl = el("span", "amt", h2s);
      amtEl.textContent = st.amount;
      h2s.appendChild(document.createTextNode(h2.slice(ai + st.amount.length)));
      col.appendChild(document.createTextNode(post));
      M.h2Span = h2s;
    } else {
      col.textContent = ctext;
    }
    off = b;
  }
  if (!amtEl) {
    // statute excerpt lacks (h)(2): append it as its own column tail
    const col = wall.lastChild;
    const h2s = el("span", "h2", col);
    h2s.textContent = "\n\n";
    amtEl = el("span", "amt", h2s);
    amtEl.textContent = st.amount;
    M.h2Span = h2s;
  }
  for (const col of wall.children) col._words = (col.textContent.match(/\S+/g) || []).length;
  V.statute.words = [...wall.children].reduce((a, c) => a + c._words, 0);
  wordCount = el("div", "note", stage);
  css(wordCount, { left: "50%", top: H / 2 + (VERT ? 230 : 190) + "px", transform: "translateX(-50%)", fontSize: "30px", color: "var(--ink-2)" });
  amtBox = el("div", "", stage); amtBox.id = "amtBox";
  lawChip = el("div", "chip", stage);
  lawChip.textContent = st.cite;

  quote = el("div", "", stage); quote.id = "quote";
  const q = el("div", "q", quote);
  const qBreak = V.quote.text.indexOf(" that ");
  quoteWords = [];
  V.quote.text.split(/(?<= )/).forEach((w, i, arr) => {
    const s = el("span", "", q); s.textContent = w; quoteWords.push(s);
    if (V.quote.text.slice(0, arr.slice(0, i + 1).join("").length).length === qBreak + 1) el("br", "", q);
  });
  quoteAttr = el("div", "attr", quote, V.quote.attr);

  // --- scene 2: code
  code = el("div", "", stage); code.id = "code";
  const bar = el("div", "bar", code);
  bar.innerHTML = `<span>policyengine-us /</span><b>${V.code.file}</b>`;
  const pre = el("pre", "", code);
  codeLines = V.code.lines.map((ln, i) => {
    const d = el("span", "ln", pre);
    const hl = el("span", "hl", d);
    el("span", "no", d).textContent = V.code.first + i;
    d.insertAdjacentHTML("beforeend", highlightYaml(ln.slice(V.code.dedent || 0)));
    d._hl = hl;
    return d;
  });
  codeVal = codeLines[V.code.valueLine - V.code.first].querySelector(".v");
  codeRefLine = codeLines[V.code.refLine - V.code.first];
  css(code, { left: L.code.x + "px", top: L.code.y + "px", width: L.code.w + "px" });

  token = el("div", "", stage); token.id = "token";
  tokA = el("span", "a", token); tokA.textContent = st.amount;
  tokB = el("span", "b", token); tokB.textContent = fmtYaml(V.reform.from);

  cap1 = buildCaption([["PolicyEngine turns the law into "], ["code.", "t"]], "", stage);
  css(cap1, { left: L.cap.x + "px", top: L.cap.y + "px", width: L.cap.w + "px", fontSize: L.cap.size + "px" });

  cap2 = buildCaption([["What if Congress raised the credit to "], ["$" + fmt(V.reform.to) + "?", "t"]], "", stage);
  css(cap2, { left: L.cap.x + "px", top: L.cap.y + "px", width: L.cap.w + "px", fontSize: L.cap.size + "px" });

  // the reform as passed to pe.us.calculate_household (household.json meta.reform_dict_passed);
  // national.py passes the same parameter, period and value as a Policy
  reform = el("div", "", stage); reform.id = "reform";
  reform.innerHTML = `<pre></pre>`;
  const [rPath] = Object.keys(V.reform.dict);
  const [rPeriod] = Object.keys(V.reform.dict[rPath]);
  const rpre = reform.querySelector("pre");
  const rl = [
    `<span class="k">reform</span> = {`,
    `    <span class="s">"${rPath}"</span>: {`,
    `        <span class="s">"${rPeriod}"</span>: <span class="v n">${V.reform.dict[rPath][rPeriod]}</span>,`,
    `    },`,
    `}`,
  ];
  reformLines = rl.map((h) => { const d = el("span", "ln", rpre); d.innerHTML = h; return d; });
  reformVal = reform.querySelector(".v");
  css(reform, { left: L.reform.x + "px", top: L.reform.y + "px", width: L.reform.w + "px" });

  // --- scene 3: one family
  famWrap = el("div", "", stage); famWrap.id = "family";
  famWrap.innerHTML = familySvg();
  css(famWrap, { left: L.fam.x + "px", top: L.fam.y + "px" });
  famSvg = famWrap.querySelector("svg");
  famDesc = el("div", "", stage); famDesc.id = "famDesc";
  famDesc.innerHTML = V.household.who;
  css(famDesc, { left: L.famDesc.x + "px", top: L.famDesc.y + "px", width: L.famDesc.w + "px" });

  // the same family at every earnings level (earnings_sweep.json), one computed point per $250
  const cv3 = V.household.curve;
  const C = L.chart3, padL = 110, padB = 96, padT = 56, padR = 20;
  const gx = (e) => padL + (e / cv3.xMax) * (C.w - padL - padR);
  const yMax = 1800;
  const gy = (g) => C.h - padB - (g / yMax) * (C.h - padB - padT);
  M.gx = gx; M.gy = gy;
  chart = el("div", "", stage); chart.id = "chart3";
  css(chart, { left: C.x + "px", top: C.y + "px", width: C.w + "px", height: C.h + "px" });
  const xt = [0, 40000, 80000, 120000].filter((e) => e <= cv3.xMax);
  const yt = [0, 800, 1600];
  const d = cv3.points.map(([e, g], i) => `${i ? "L" : "M"}${gx(e).toFixed(1)},${gy(g).toFixed(1)}`).join("");
  chart.innerHTML = `<svg width="${C.w}" height="${C.h}" viewBox="0 0 ${C.w} ${C.h}">
    ${yt.map((g) => `<line class="grid" x1="${padL}" x2="${C.w - padR}" y1="${gy(g)}" y2="${gy(g)}"/>
      <text class="ty" x="${padL - 16}" y="${gy(g) + 9}" text-anchor="end">${g ? "+$" + fmt(g) : "$0"}</text>`).join("")}
    ${xt.map((e) => `<text class="tx" x="${gx(e)}" y="${C.h - padB + 40}" text-anchor="middle">${e ? "$" + e / 1000 + "k" : "$0"}</text>`).join("")}
    <text class="ax" x="${(padL + C.w - padR) / 2}" y="${C.h - 6}" text-anchor="middle">Earnings</text>
    <text class="ax" x="${padL}" y="24" text-anchor="start">Change in net income, ${V.reform.year}</text>
    <path class="curve" d="${d}"/>
    <circle class="ph" r="9"/>
  </svg>`;
  // source tag: on the axis-title line in landscape; a line below the chart in portrait,
  // where the narrower chart would run it into "Earnings"
  const srcCurve = el("div", "src", chart);
  srcCurve.innerHTML = (V.sources?.curve || []).join("<br>");
  css(srcCurve, { right: padR + "px", top: (VERT ? C.h + 10 : C.h - 27) + "px", opacity: 1 });
  chartSvg = chart.querySelector("svg");
  curvePath = chart.querySelector(".curve");
  playhead = chart.querySelector(".ph");
  M.curveLen = null;
  pinEl = el("div", "pin", chart);
  pinEl.innerHTML = `$${fmt(cv3.pin[0])}<b>+$${fmt(cv3.pin[1])}</b>`;
  css(pinEl, { left: gx(cv3.pin[0]) + "px", top: gy(cv3.pin[1]) + "px" });
  lineEls = cv3.lines.map((txt, i) => {
    const e = el("div", "line3" + (i ? " t" : ""), stage);
    e.textContent = txt;
    css(e, { left: L.lines3.x + "px", top: L.lines3.y + i * L.lines3.size * 1.15 + "px", fontSize: L.lines3.size + "px" });
    return e;
  });
  noteEl = el("div", "sub", stage);
  noteEl.textContent = cv3.note;
  css(noteEl, { left: L.lines3.x + "px", top: L.lines3.y + 2 * L.lines3.size * 1.15 + 18 + "px", width: (VERT ? 936 : 1000) + "px" });

  reformChip = el("div", "chip", stage);
  reformChip.innerHTML = `Child Tax Credit $${fmt(V.reform.from)} → $${fmt(V.reform.to)} in ${V.reform.year}`;

  // --- scene 4-5: everyone
  capNation = buildCaption(V.nation.caption.map((c, i) => [c, i % 2 ? "t" : ""]), "", stage);
  css(capNation, { left: L.capTop.x + "px", top: L.capTop.y + "px", width: L.capTop.w + "px", fontSize: L.capTop.size + "px" });
  statEls = V.nation.stats.map((s, i) => {
    const d = el("div", "stat", stage);
    d.innerHTML = `<div class="num${i === 0 ? "" : " t"}"></div><div class="what">${s.what}</div>`;
    css(d, VERT
      ? { left: L.stats.x + (i % 2) * 490 + "px", top: L.stats.y + Math.floor(i / 2) * L.stats.gap + "px", width: "450px" }
      : { left: L.stats.x + "px", top: L.stats.y + i * L.stats.gap + "px" });
    d._num = d.querySelector(".num");
    return d;
  });
  legendDots = el("div", "sub", stage);
  legendDots.innerHTML = V.nation.dotNote;
  css(legendDots, { left: L.legend.x + "px", top: L.legend.y + "px", width: (VERT ? 936 : 1200) + "px" });
  // what the national figures are computed with, in the scene's bottom-right corner
  srcNation = sourceTag(V.sources?.nation, VERT ? { right: L.margin, bottom: 340 } : { right: L.margin, bottom: 44 });

  if (V.deciles) {
    capDist = buildCaption(V.deciles.caption.map((c, i) => [c, i % 2 ? "t" : ""]), "", stage);
    css(capDist, { left: L.capTop.x + "px", top: L.capTop.y + "px", width: L.capTop.w + "px", fontSize: L.capTop.size + "px" });
    for (let i = 0; i < 10; i++) {
      barLbl.push(el("div", "barv", stage));
      barAx.push(el("div", "barx", stage, String(i + 1)));
    }
    axEnds = [el("div", "barend", stage, "Lowest income"), el("div", "barend", stage, "Highest income")];
    srcDeciles = sourceTag(V.sources?.deciles, {});  // placed under the bars in buildDeciles
  }

  // --- scene 6: sign-off
  logoImg = el("img", "", stage); logoImg.id = "logo";
  logoImg.src = "/site/logo-white.svg";
  tagEl = el("div", "", stage); tagEl.id = "tag";
  tagEl.textContent = "Computing public policy for everyone.";
  urlEl = el("div", "", stage); urlEl.id = "url";
  urlEl.innerHTML = V.signoff;

  // --- finishing layers
  grainCv = el("canvas", "layer", stage); grainCv.id = "grain";
  grainCv.width = 480; grainCv.height = Math.round(480 * H / W);
  grainCtx = grainCv.getContext("2d");
  el("div", "layer", stage).id = "vignette";
  mockBanner = el("div", "", stage); mockBanner.id = "mockBanner";
  mockBanner.textContent = "MOCK DATA — PLACEHOLDER NUMBERS, NOT POLICYENGINE OUTPUT";
  if (V.mock) mockBanner.style.display = "block";
}


function highlightYaml(line) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const m = line.match(/^(\s*)(#.*)$/);
  if (m) return `${m[1]}<span class="c">${esc(m[2])}</span>`;
  const kv = line.match(/^(\s*)(- )?([\w-]+)(:)(.*)$/);
  if (!kv) return esc(line);
  const [, ind, dash = "", key, colon, rest] = kv;
  let restHtml = esc(rest);
  if (/^\s*[\d_]+\s*$/.test(rest)) restHtml = ` <span class="v n">${esc(rest.trim())}</span>`;
  else if (rest.trim()) restHtml = ` <span class="s">${esc(rest.trim())}</span>`;
  const keyCls = /^\d{4}-\d{2}-\d{2}$/.test(key) ? "d" : "k";
  return `${ind}${esc(dash)}<span class="${keyCls}">${esc(key)}</span>${colon}${restHtml}`;
}

function familySvg() {
  // Two adults, two children (ages 4 and 8), drawn as simple figures.
  const fig = (x, h, head, w) => {
    const top = 260 - h;
    return `<g transform="translate(${x},0)">
      <circle cx="0" cy="${top + head}" r="${head}" />
      <rect x="${-w / 2}" y="${top + head * 2 + 10}" width="${w}" height="${h - head * 2 - 10}" rx="${w / 2}" />
    </g>`;
  };
  return `<svg width="560" height="280" viewBox="0 0 560 280">
    <g fill="rgba(56,178,172,0.10)" stroke="#81E6D9" stroke-width="4">
      ${fig(80, 240, 30, 84)}${fig(210, 232, 29, 80)}${fig(340, 150, 22, 58)}${fig(460, 178, 25, 66)}
    </g>
    <line x1="10" y1="268" x2="550" y2="268" stroke="#334155" stroke-width="2"/>
  </svg>`;
}

// ------------------------------------------------------------- measurement
function rectOf(e) {
  const r = e.getBoundingClientRect();
  const s = stage.getBoundingClientRect();
  const k = s.width / W;
  return { x: (r.left - s.left) / k, y: (r.top - s.top) / k, w: r.width / k, h: r.height / k };
}

function measure() {
  // wall-local coordinates of the $2,200 token (wall untransformed)
  wallCam.style.transform = "none";
  const wr = rectOf(wall), ar = rectOf(amtEl), hr = rectOf(M.h2Span);
  M.amt = { x: ar.x - wr.x, y: ar.y - wr.y, w: ar.w, h: ar.h };
  M.h2 = { x: hr.x - wr.x, y: hr.y - wr.y, w: hr.w, h: hr.h };
  M.wall = { w: wr.w, h: wr.h };
  // code value position with the panel at rest
  css(code, { opacity: 1, transform: "none" });
  const vr = rectOf(codeVal);
  M.val = vr;
  M.valFont = 22;
  M.codeRect = rectOf(code);
  M.ref = rectOf(codeRefLine);
  // when the playhead reaches the pinned earnings level (solved once, so frames stay history-free)
  M.curveLen = curvePath.getTotalLength();
  const pinX = M.gx(V.household.curve.pin[0]);
  let lo = 0, hi = 1;
  for (let k = 0; k < 40; k++) {
    const mid = (lo + hi) / 2;
    if (curvePath.getPointAtLength(M.curveLen * E.inOutSine(mid)).x < pinX) lo = mid; else hi = mid;
  }
  M.pinT = lerp(T.curveA, T.curveB, hi);
}

// camera over the statute wall: focus point (wall coords) drawn at screen (cx, cy)
function wallCamera(t) {
  const cx = W / 2, cy = H / 2;
  const amtC = { x: M.amt.x + M.amt.w / 2, y: M.amt.y + M.amt.h / 2 };
  const wc = { x: M.wall.w / 2, y: M.wall.h / 2 };
  // wide: the whole section fits the frame; slow push while it pours in
  const fitS = Math.min((W - 80) / M.wall.w, (H - 60) / M.wall.h);
  const s0 = fitS, s1 = fitS * 1.12, sEnd = VERT ? 3.6 : 4.2;
  const push = P(t, 0, T.quoteOut, E.inOutSine);
  const dive = P(t, T.quoteOut - 0.1, T.flyStart + 0.05, E.inOutCubic);
  const s = Math.exp(lerp(Math.log(lerp(s0, s1, push)), Math.log(sEnd), dive));
  const drift = 1 + 0.18 * P(t, T.flyStart, T.flyStart + 1.2, E.outCubic);
  const S = s * drift;
  const d0 = T.quoteOut - 0.1;
  if (t < d0) return { s: S, tx: cx - wc.x * S, ty: cy - wc.y * S };
  // dive: scale about the amount while it glides to screen centre, so it never leaves frame
  const ax0 = cx + (amtC.x - wc.x) * s1, ay0 = cy + (amtC.y - wc.y) * s1;
  const g = P(t, d0, T.flyStart + 0.05, E.inOutSine);
  const ax = lerp(ax0, cx, g), ay = lerp(ay0, cy, g);
  return { s: S, tx: ax - amtC.x * S, ty: ay - amtC.y * S };
}

// --------------------------------------------------------------- scenes
function scene1(t) {
  const vis = t < T.flyStart + 1.3;
  wallCam.style.display = vis ? "block" : "none";
  if (vis) {
    const c = wallCamera(t);
    const fade = 1 - P(t, T.flyStart + 0.1, T.flyStart + 0.6, E.inOutSine);
    const blur = 6 * P(t, T.flyStart, T.flyStart + 1.1);
    css(wallCam, {
      transform: `translate(${c.tx}px, ${c.ty}px) scale(${c.s})`,
      opacity: lerp(0.6, 1, P(t, 0, 0.5)) * fade,
      filter: blur > 0.05 ? `blur(${blur}px)` : "none",
    });
    // the section pours in column by column, in reading order
    const ncol = wall.children.length;
    [...wall.children].forEach((col, i) => {
      const a = T.pourA + (i * (T.pourB - T.pourA - 0.35)) / ncol;
      const p = P(t, a, a + 0.35 + (T.pourB - T.pourA) / ncol, E.inOutSine);
      const m = `linear-gradient(to bottom, #000 ${p * 100}%, transparent ${p * 100 + 6}%)`;
      col.style.webkitMaskImage = m; col.style.maskImage = m;
    });
    wordCount.textContent = `${V.statute.cite.replace(/\(h\)\(2\)$/, "").trim()} · ${fmt(V.statute.words)} words`;
    const wc = P(t, 0, 0.5, E.outCubic);
    css(wordCount, { opacity: wc * (1 - P(t, T.quoteOut - 0.1, T.quoteOut + 0.3, E.inOutSine)), filter: `blur(${lerp(8, 0, wc)}px)` });
    // dim the wall behind the quote
    const qv = env(t, 0.4, 0.9, T.quoteOut, T.quoteOut + 0.4);
    wall.style.opacity = 1 - 0.5 * qv;
    // (h)(2) paragraph brightens, then the amount box draws in
    const lit = P(t, T.lawFocus - 0.35, T.lawFocus + 0.15, E.outCubic);
    M.h2Span.style.color = mix("#3A4658", "#E2E8F0", lit);
    const bx = P(t, T.zoomAmt, T.zoomAmt + 0.35, E.outBack);
    const boxFade = 1 - P(t, T.flyStart - 0.05, T.flyStart + 0.2);
    const ax = c.tx + M.amt.x * c.s, ay = c.ty + M.amt.y * c.s;
    const pad = 5 * c.s;
    css(amtBox, {
      left: ax - pad + "px", top: ay - pad * 0.5 + "px",
      width: M.amt.w * c.s + pad * 2 + "px", height: M.amt.h * c.s + pad + "px",
      opacity: bx * boxFade, transform: `scale(${lerp(1.25, 1, bx)})`,
    });
    amtEl.style.visibility = t >= T.flyStart ? "hidden" : "visible";
    if (t < T.refIn - 0.2) {
      const chipV = env(t, T.zoomAmt + 0.1, T.zoomAmt + 0.35, T.flyStart + 0.3, T.flyStart + 0.55);
      css(lawChip, {
        left: ax + (M.amt.w * c.s) / 2 + "px", top: ay - 74 + "px",
        opacity: chipV, transform: `translate(-50%, ${lerp(12, 0, chipV)}px)`,
      });
    }
  } else {
    css(amtBox, { opacity: 0 });
    wordCount.style.opacity = 0;
  }
  // the same citation chip docks on the code line that cites it
  if (t >= T.refIn - 0.2) {
    const cv2 = env(t, T.refIn, T.refIn + 0.35, T.cap2In - 0.1, T.cap2In + 0.3);
    css(lawChip, {
      left: M.codeRect.x + M.codeRect.w - 28 + "px", top: M.ref.y - 58 + "px",
      opacity: cv2, transform: `translate(-100%, ${lerp(10, 0, cv2)}px)`,
    });
  }

  // quote
  const qOut = P(t, T.quoteOut, T.quoteOut + 0.45, E.inCubic);
  quote.style.display = t < T.quoteOut + 0.5 ? "block" : "none";
  quoteWords.forEach((w, i) => {
    const p = P(t, T.quoteIn + i * T.qStag, T.quoteIn + i * T.qStag + 0.45, E.outCubic);
    css(w, {
      opacity: p * (1 - qOut),
      transform: `translateY(${lerp(18, 0, p) - 24 * qOut}px)`,
      filter: `blur(${lerp(10, 0, p) + 8 * qOut}px)`,
    });
  });
  const ap = P(t, T.quoteIn + quoteWords.length * T.qStag, T.quoteIn + quoteWords.length * T.qStag + 0.4, E.outCubic);
  css(quoteAttr, { opacity: ap * (1 - qOut), transform: `translateY(${lerp(10, 0, ap)}px)` });
}

function scene2(t) {
  // code panel
  const inP = P(t, T.codeIn, T.codeIn + 0.6, E.outQuint);
  const outP = P(t, T.famIn - 0.2, T.famIn + 0.35, E.inCubic);
  const vis = t > T.codeIn - 0.01 && t < T.famIn + 0.4;
  code.style.display = vis ? "block" : "none";
  if (vis) {
    css(code, {
      opacity: inP * (1 - outP),
      transform: `translate(${lerp(60, 0, inP) + 200 * outP}px, 0) scale(${lerp(0.96, 1, inP)})`,
    });
    // other lines stay dim until the token lands, so the eye goes to line 11
    const vi = V.code.valueLine - V.code.first;
    const undim = lerp(0.3, 1, P(t, T.flyEnd, T.flyEnd + 0.35, E.outCubic));
    codeLines.forEach((d, i) => {
      const p = P(t, T.codeIn + 0.15 + i * 0.032, T.codeIn + 0.15 + i * 0.032 + 0.18, E.outCubic);
      css(d, { opacity: p * (i === vi ? 1 : undim), transform: `translateX(${lerp(-14, 0, p)}px)` });
    });
    // the flown-in value lands at flyEnd
    codeVal.style.visibility = t >= T.flyEnd ? "visible" : "hidden";
    const land = env(t, T.flyEnd - 0.02, T.flyEnd + 0.1, T.flyEnd + 0.5, T.flyEnd + 1.1);
    const rf = env(t, T.reformVal, T.reformVal + 0.25, T.famIn - 0.3, T.famIn);
    codeLines[vi]._hl.style.opacity = Math.max(land, 0.55 * P(t, T.flyEnd + 0.5, T.flyEnd + 0.8) * (1 - outP), rf);
    // the citation line lights up
    const refV = env(t, T.refIn, T.refIn + 0.3, T.cap2In, T.cap2In + 0.4);
    codeRefLine._hl.style.opacity = refV;
    // line 17 (the file's own note on 2021) stays in plain comment grey: no emphasis
  }

  // the $2,200 token flight: statute (serif) -> code (mono)
  const fp = P(t, T.flyStart, T.flyEnd, E.inOutCubic);
  const flying = t >= T.flyStart && t < T.flyEnd;
  token.style.opacity = flying ? 1 : 0;
  if (flying) {
    const c = wallCamera(T.flyStart);
    const sx = c.tx + M.amt.x * c.s, sy = c.ty + M.amt.y * c.s;
    const sSize = 21 * c.s;
    const ex = M.val.x, ey = M.val.y;
    // quadratic arc
    const mx = lerp(sx, ex, 0.5), my = Math.min(sy, ey) - (VERT ? 60 : 80);
    const x = (1 - fp) ** 2 * sx + 2 * (1 - fp) * fp * mx + fp * fp * ex;
    const y = (1 - fp) ** 2 * sy + 2 * (1 - fp) * fp * my + fp * fp * ey;
    const size = Math.exp(lerp(Math.log(sSize), Math.log(M.valFont), fp));
    const k = P(fp, 0.35, 0.7);
    css(token, { transform: `translate(${x}px, ${y}px)`, fontSize: size + "px", lineHeight: 1.25 });
    css(tokA, { opacity: 1 - k, color: mix("#E2E8F0", "#B2F5EA", P(fp, 0, 0.15)), filter: `drop-shadow(0 0 ${(12 * (1 - fp) + 4) * P(fp, 0, 0.15)}px rgba(79,209,197,.8))` });
    css(tokB, { opacity: k, filter: `drop-shadow(0 0 ${10 * fp}px rgba(79,209,197,.8))` });
  }

  // captions
  const c1 = t > T.cap1In - 0.01 && t < T.cap2In + 0.5;
  cap1.style.display = c1 ? "block" : "none";
  if (c1) wordsIn(cap1, t, T.cap1In, 0.07, T.cap2In, 0.35);

  const c2 = t > T.cap2In && t < T.famIn + 0.4;
  cap2.style.display = c2 ? "block" : "none";
  if (c2) wordsIn(cap2, t, T.cap2In + 0.05, 0.05, T.famIn - 0.1, 0.3);

  const rv = env(t, T.reformIn, T.reformIn + 0.35, T.famIn - 0.2, T.famIn + 0.15);
  reform.style.display = rv > 0.001 ? "block" : "none";
  if (rv > 0.001) {
    css(reform, { opacity: rv, transform: `translateY(${lerp(24, 0, rv)}px)` });
    reformLines.forEach((d, i) => {
      const p = P(t, T.reformIn + 0.1 + i * 0.06, T.reformIn + 0.3 + i * 0.06, E.outCubic);
      css(d, { opacity: p, transform: `translateX(${lerp(-10, 0, p)}px)` });
    });
    const vp = P(t, T.reformVal, T.reformVal + 0.3, E.outCubic);
    css(reformVal, { color: mix("#F5F5F5", "#81E6D9", vp), textShadow: `0 0 ${18 * vp}px rgba(79,209,197,${0.8 * vp})` });
  }
}

function wordsIn(cap, t, a, stagger, out, outDur) {
  const ws = cap.children;
  const o = P(t, out, out + outDur, E.inCubic);
  for (let i = 0; i < ws.length; i++) {
    const p = P(t, a + i * stagger, a + i * stagger + 0.5, E.outQuint);
    css(ws[i], {
      opacity: p * (1 - o),
      transform: `translateY(${lerp(0.5, 0, p) - 0.3 * o}em)`,
      filter: `blur(${lerp(8, 0, p) + 6 * o}px)`,
    });
  }
}

function scene3(t) {
  const vis = t > T.famIn - 0.01 && t < T.zoomA + 0.6;
  for (const e of [famWrap, famDesc, chart, noteEl, ...lineEls]) e.style.display = vis ? "block" : "none";
  if (!vis) return;
  const out = P(t, T.famOut, T.famOut + 0.45, E.inCubic);
  // family figures pop in one by one; at the cut they collapse into a dot
  const figs = famSvg.querySelectorAll("g > g");
  figs.forEach((g, i) => {
    const p = P(t, T.famIn + 0.3 + i * 0.09, T.famIn + 0.3 + i * 0.09 + 0.5, E.outBack);
    g.setAttribute("opacity", clamp(p));
    const cx = [80, 210, 340, 460][i];
    g.setAttribute("transform", `translate(${cx},${lerp(40, 0, clamp(p))})`);
  });
  const shrink = P(t, T.famOut, T.zoomA + 0.05, E.inOutCubic);
  const famCx = L.fam.x + 280, famCy = L.fam.y + 150;
  css(famWrap, {
    opacity: P(t, T.famIn + 0.2, T.famIn + 0.45) * (1 - P(t, T.zoomA - 0.05, T.zoomA + 0.1)),
    transform: `translate(${(W / 2 - famCx) * shrink}px, ${(H / 2 - famCy) * shrink}px) scale(${lerp(1, 0.02, shrink)})`,
    transformOrigin: "280px 150px",
  });
  const dp = P(t, T.famIn + 0.35, T.famIn + 0.9, E.outCubic);
  css(famDesc, { opacity: dp * (1 - out), transform: `translateY(${lerp(16, 0, dp)}px)` });

  // the chart: axes, then the computed curve drawn left to right with a playhead
  const cp = P(t, T.chartIn, T.chartIn + 0.45, E.outCubic);
  css(chart, { opacity: cp * (1 - out), transform: `translateY(${lerp(18, 0, cp)}px)` });
  const u = P(t, T.curveA, T.curveB, E.inOutSine);
  const len = M.curveLen;
  curvePath.style.strokeDasharray = `${len} ${len}`;
  curvePath.style.strokeDashoffset = `${len * (1 - u)}`;
  const pt = curvePath.getPointAtLength(len * u);
  playhead.setAttribute("cx", pt.x); playhead.setAttribute("cy", pt.y);
  playhead.style.opacity = u > 0 && u < 1 ? 1 : P(t, T.curveB, T.curveB + 0.3) > 0 ? 1 - P(t, T.curveB, T.curveB + 0.3) : 0;
  // the in-between point is pinned once the playhead passes it
  const pp = P(t, M.pinT, M.pinT + 0.3, E.outBack);
  css(pinEl, { opacity: clamp(pp), transform: `translate(-50%, calc(-100% - 22px)) scale(${lerp(0.7, 1, clamp(pp))})` });
  // the two facts, then the rule behind them
  lineEls.forEach((e, i) => {
    const at = i ? T.line2 : T.line1;
    const lp = P(t, at, at + 0.4, E.outCubic);
    css(e, { opacity: lp * (1 - out), transform: `translateY(${lerp(0.4, 0, lp)}em)`, filter: `blur(${lerp(8, 0, lp)}px)` });
  });
  const np = P(t, T.noteIn, T.noteIn + 0.45, E.outCubic);
  css(noteEl, { opacity: np * (1 - out), transform: `translateY(${lerp(12, 0, np)}px)` });
}

// ---------------------------------------------------------- dots & map
const RAMP = ["#1E293B", "#285E61", "#319795", "#4FD1C5", "#B2F5EA"];
function rampColor(u) {
  u = clamp(u);
  const k = u * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(k));
  return mix(RAMP[i], RAMP[i + 1], k - i);
}

function buildMap() {
  const states = feature(statesTopo, statesTopo.objects.states);
  const proj = geoAlbersUsa().fitExtent(L.mapBox, states);
  const path = geoPath(proj);
  map.proj = proj;
  map.paths = new Map();
  for (const f of states.features) map.paths.set(+f.id, new Path2D(path(f)));
  map.bounds = new Map(states.features.map((f) => [+f.id, path.bounds(f)]));
  map.outline = new Path2D(states.features.map((f) => path(f)).join(""));
  const home = V.household.lonlat || [-82.9988, 39.9612];
  map.home = proj(home);

  // congressional district shapes (Census cb_2024 cd119, via policyengine-app-v2)
  map.cd = new Map();
  for (const d of V.cdGeo || []) {
    const f = { type: "Feature", geometry: { type: "MultiPolygon", coordinates: d.polys } };
    const pth = path(f);
    if (pth) map.cd.set(d.geoid, { p2: new Path2D(pth), b: path.bounds(f) });
  }
  const rnd = mulberry32(20260924);
  const probe = document.createElement("canvas").getContext("2d");
  const sample = V.sample;
  const maxGain = V.nation.dotMax || 3200;
  dots = [];
  let viaDistrict = 0;
  for (let i = 0; i < sample.length; i++) {
    const [fips, gain, cd, dec] = sample[i];
    const g = (cd && map.cd.get(cd)) || null;
    const b = g ? g.b : map.bounds.get(fips), p2 = g ? g.p2 : map.paths.get(fips);
    if (!b || !p2) continue;
    if (g) viaDistrict++;
    let x, y, tries = 0;
    do {
      x = lerp(b[0][0], b[1][0], rnd()); y = lerp(b[0][1], b[1][1], rnd()); tries++;
    } while (!probe.isPointInPath(p2, x, y) && tries < 400);
    // light-up order follows the reform's $800-per-child structure: one child's
    // worth first, then two, then three or more
    const step = gain > 0.5 ? Math.min(3, Math.max(1, Math.round(gain / 800))) : 0;
    // per-dot jitter from its own seed, so timing (and the score) is identical in every layout
    dots.push({ x, y, gain, cd, fips, dec, step, u: clamp(gain / maxGain), j: mulberry32(i * 7919 + 17)() });
  }
  map.viaDistrict = viaDistrict;
  const span = T.rippleB - T.rippleA - 0.35;
  for (const d of dots) d.lightT = T.rippleA + ((d.step - 1) / 2) * span * 0.75 + d.j * 0.35;
}

// A chart's small print: which model and data produced it, right-aligned in its corner.
function sourceTag(lines, pos) {
  const d = el("div", "src", stage);
  d.innerHTML = (lines || []).join("<br>");
  css(d, Object.fromEntries(Object.entries(pos).map(([k, v]) => [k, v + "px"])));
  return d;
}

function buildDeciles() {
  if (!V.deciles) return;
  const [[bx0, by0], [bx1, by1]] = L.chart;
  const n = 10, gap = VERT ? 16 : 24;
  const w = (bx1 - bx0 - gap * (n - 1)) / n;
  const max = Math.max(...V.deciles.avg);
  const k = (by1 - by0 - 70) / max;
  bars = V.deciles.avg.map((v, i) => ({ i, v, x: bx0 + i * (w + gap), w, h: v * k, base: by1, inT: T.hexFill + i * 0.07 }));
  const rnd = mulberry32(7);
  for (const d of dots) {
    const b = d.dec >= 1 && d.dec <= 10 ? bars[d.dec - 1] : null;
    if (!b) continue;
    d.hx = b.x + 5 + rnd() * (b.w - 10); d.hy = b.base - 3 - rnd() * 9;
  }
  bars.forEach((b, i) => {
    css(barLbl[i], { left: b.x + b.w / 2 + "px" });
    css(barAx[i], { left: b.x + b.w / 2 + "px", top: b.base + 14 + "px" });
  });
  css(axEnds[0], { left: bars[0].x + "px", top: by1 + 58 + "px" });
  css(axEnds[1], { left: bars[9].x + bars[9].w + "px", top: by1 + 58 + "px", transform: "translateX(-100%)" });
  css(srcDeciles, { right: W - (bars[9].x + bars[9].w) + "px", top: by1 + 58 + 46 + "px" });
}

function buildLogoPoints() {
  // rasterize the wordmark and sample filled pixels as dot targets
  const w = L.logo.w, h = Math.round((w * 207) / 996);
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d");
  g.drawImage(logoImg, 0, 0, w, h);
  const data = g.getImageData(0, 0, w, h).data;
  const pts = [];
  const step = 3;
  for (let y = 0; y < h; y += step)
    for (let x = 0; x < w; x += step)
      if (data[(y * w + x) * 4 + 3] > 40) pts.push([L.logo.cx - w / 2 + x, L.logo.cy - h / 2 + y, data[(y * w + x) * 4 + 3] < 140]);
  const rnd = mulberry32(11);
  for (let i = pts.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [pts[i], pts[j]] = [pts[j], pts[i]]; }
  logoPts = pts;
  M.logoH = h;
  // assign targets: sort both by x so the swarm sweeps instead of crossing
  const order = dots.map((d, i) => i).sort((a, b) => (dots[a].hx ?? dots[a].x) - (dots[b].hx ?? dots[b].x));
  const tgt = dots.map((_, i) => pts[i % pts.length]).sort((a, b) => a[0] - b[0]);
  order.forEach((di, k) => { dots[di].lx = tgt[k][0]; dots[di].ly = tgt[k][1]; dots[di].rail = tgt[k][2]; });
}

let sprites = null;
function makeSprites() {
  // pre-rendered glowing dots in 24 ramp steps plus a neutral gray
  sprites = [];
  const R = 7 * DPR;
  for (let i = 0; i <= 24; i++) {
    const c = document.createElement("canvas");
    c.width = c.height = R * 2;
    const g = c.getContext("2d");
    const col = i === 0 ? "#4E5D72" : rampColor(0.25 + 0.75 * (i / 24));
    if (i > 0) {
      const grd = g.createRadialGradient(R, R, 0, R, R, R);
      grd.addColorStop(0, col.replace("rgb", "rgba").replace(")", ",0.16)"));
      grd.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = grd; g.fillRect(0, 0, R * 2, R * 2);
    }
    g.fillStyle = col;
    g.beginPath(); g.arc(R, R, 2.3 * DPR, 0, Math.PI * 2); g.fill();
    sprites.push(c);
  }
}

function mapCamera(t) {
  const u = P(t, T.zoomA, T.zoomB, (x) => 1 - Math.pow(1 - E.inOutSine(x), 2.2));
  const s0 = VERT ? 6 : 8;
  const s = Math.exp(lerp(Math.log(s0), 0, u));
  const sx = lerp(W / 2, map.home[0], u), sy = lerp(H / 2, map.home[1], u);
  return { s, fx: map.home[0], fy: map.home[1], sx, sy };
}

function drawDots(t) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  // reset all drawing state: a frame must not inherit anything from the last one
  ctx.globalAlpha = 1; ctx.lineCap = "round"; ctx.lineWidth = 1;
  ctx.strokeStyle = "#000"; ctx.fillStyle = "#000";
  if (t < T.zoomA - 0.1 || t > DUR) return;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  const cam = mapCamera(t);
  const toS = (x, y) => [cam.sx + (x - cam.fx) * cam.s, cam.sy + (y - cam.fy) * cam.s];
  const appear = P(t, T.zoomA - 0.05, T.zoomA + 0.45, E.outCubic);

  // state outlines under the dots while the map is up
  const outlineA = 0.5 * appear * (1 - P(t, T.hexA, T.hexA + 0.6));
  if (outlineA > 0.01) {
    ctx.save();
    ctx.translate(cam.sx - cam.fx * cam.s, cam.sy - cam.fy * cam.s);
    ctx.scale(cam.s, cam.s);
    ctx.lineWidth = 1.1 / cam.s;
    ctx.strokeStyle = `rgba(71, 85, 105, ${outlineA})`;
    ctx.stroke(map.outline);
    ctx.restore();
  }

  // income-decile bars (averages from the full national run, not the sample)
  const hexOut = P(t, T.logoA, T.logoA + 0.5, E.inCubic);
  if (bars.length && t > T.hexFill - 0.05 && hexOut < 1) {
    ctx.strokeStyle = `rgba(71,85,105,${1 - hexOut})`;
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(bars[0].x - 10, bars[0].base + 0.5); ctx.lineTo(bars[9].x + bars[9].w + 10, bars[0].base + 0.5); ctx.stroke();
    for (const b of bars) {
      const p = P(t, b.inT, b.inT + 0.55, E.outCubic);
      if (p <= 0) continue;
      const h = Math.max(2, b.h) * p * (1 - hexOut);
      const g = ctx.createLinearGradient(0, b.base - b.h, 0, b.base);
      g.addColorStop(0, "#81E6D9"); g.addColorStop(1, "#2C7A7B");
      ctx.fillStyle = g;
      ctx.globalAlpha = 0.92 * (1 - hexOut);
      ctx.beginPath();
      ctx.roundRect(b.x, b.base - h, b.w, h, [Math.min(6, h / 2), Math.min(6, h / 2), 0, 0]);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  // the dots
  const R = 7;
  const posAt = (d, tt) => {
    const cam = mapCamera(tt);
    let x = cam.sx + (d.x - cam.fx) * cam.s, y = cam.sy + (d.y - cam.fy) * cam.s;
    let a = P(tt, T.zoomA - 0.05, T.zoomA + 0.45, E.outCubic);
    const toHex = P(tt, T.hexA + d.j * 0.25, T.hexB - 0.25 + d.j * 0.25, E.inOutCubic);
    if (d.hx != null && toHex > 0) { x = lerp(x, d.hx, toHex); y = lerp(y, d.hy, toHex); }
    if (tt < T.logoA) a *= 1 - (d.hx != null ? P(tt, T.hexFill + 0.1, T.hexFill + 0.9) : P(tt, T.hexA, T.hexA + 0.6));
    const toLogo = P(tt, T.logoA + d.j * 0.2, T.logoB - 0.2 + d.j * 0.2, E.inOutCubic);
    if (tt >= T.logoA) {
      const sx = d.hx ?? x, sy = d.hy ?? y;
      x = lerp(sx, d.lx, toLogo); y = lerp(sy, d.ly, toLogo);
      a = P(tt, T.logoA, T.logoA + 0.3) * (1 - P(tt, T.logoB + 0.05, T.logoB + 0.7, E.inCubic));
    }
    return [x, y, a, toLogo];
  };
  const shutter = 0.5 / 60;
  ctx.lineCap = "round";
  for (const d of dots) {
    const [x, y, a, toLogo] = posAt(d, t);
    if (a <= 0.01) continue;
    if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
    const lit = d.gain > 0.5 && t >= d.lightT ? P(t, d.lightT, d.lightT + 0.25, E.outCubic) : 0;
    let si = 0;
    if (lit > 0) si = Math.max(1, Math.round((0.25 + 0.75 * d.u) * 24 * lit));
    // the logo's rails are 30% white in the SVG, so their dots stay dim
    if (toLogo > 0.2) si = d.rail ? 0 : Math.max(si, Math.round(24 * clamp(toLogo)));
    // motion streak: where the dot was half a frame ago
    const [px, py] = posAt(d, t - shutter);
    const dist = Math.hypot(x - px, y - py);
    ctx.globalAlpha = a;
    if (dist > 2.5) {
      const flight = t >= T.hexA;
      const k = Math.min(1, (flight ? 60 : 22) / dist);
      ctx.strokeStyle = si ? rampColor(0.25 + 0.75 * (si / 24)) : "#4E5D72";
      ctx.lineWidth = flight ? 3.0 : 1.6;
      ctx.globalAlpha = a * (flight ? 0.6 : 0.35);
      ctx.beginPath(); ctx.moveTo(x + (px - x) * k, y + (py - y) * k); ctx.lineTo(x, y); ctx.stroke();
      ctx.globalAlpha = a;
    }
    ctx.drawImage(sprites[si], x - R, y - R, R * 2, R * 2);
  }
  ctx.globalAlpha = 1;

  // the family we followed, as one highlighted dot
  const fa = env(t, T.zoomA - 0.05, T.zoomA + 0.15, T.zoomA + 0.9, T.zoomA + 1.3);
  if (fa > 0.01) {
    const [x, y] = toS(map.home[0], map.home[1]);
    ctx.globalAlpha = fa;
    ctx.fillStyle = "#B2F5EA";
    ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "#81E6D9"; ctx.lineWidth = 2;
    const pr = 14 + 10 * ((t * 1.6) % 1);
    ctx.globalAlpha = fa * (1 - ((t * 1.6) % 1));
    ctx.beginPath(); ctx.arc(x, y, pr, 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

function scene45(t) {
  const nvis = t > T.zoomA && t < T.hexA + 0.6;
  capNation.style.display = nvis ? "block" : "none";
  if (nvis) wordsIn(capNation, t, T.zoomA + 0.5, 0.05, T.hexA - 0.1, 0.35);
  statEls.forEach((d, i) => {
    const at = [T.stat1, T.stat2, T.stat3][i];
    const p = env(t, at, at + 0.4, T.hexA - 0.15, T.hexA + 0.25);
    d.style.display = p > 0.001 ? "block" : "none";
    if (p <= 0.001) return;
    css(d, { opacity: p, transform: `translateY(${lerp(20, 0, p)}px)` });
    d._num.innerHTML = statText(V.nation.stats[i]);
    d._num.style.filter = `blur(${lerp(8, 0, P(t, at, at + 0.45, E.outCubic))}px)`;
  });
  const ld = env(t, T.zoomA + 0.8, T.zoomA + 1.2, T.hexA - 0.1, T.hexA + 0.3);
  css(legendDots, { opacity: ld });
  srcNation.style.opacity = env(t, T.stat1, T.stat1 + 0.4, T.hexA - 0.15, T.hexA + 0.25);

  if (capDist) {
    const dvis = t > T.hexA && t < T.logoA + 0.5;
    capDist.style.display = dvis ? "block" : "none";
    if (dvis) wordsIn(capDist, t, T.hexA + 0.35, 0.05, T.logoA - 0.2, 0.35);
    const out = P(t, T.logoA - 0.3, T.logoA);
    bars.forEach((b, i) => {
      const grow = P(t, b.inT, b.inT + 0.55, E.outCubic);
      const p = P(t, b.inT + 0.4, b.inT + 0.7, E.outCubic);
      barLbl[i].textContent = "$" + fmt(b.v);
      css(barLbl[i], { top: b.base - Math.max(2, b.h) * grow - 52 + "px", opacity: p * (1 - out), transform: "translateX(-50%)" });
      css(barAx[i], { opacity: P(t, T.hexA + 0.3, T.hexA + 0.7) * (1 - out) });
    });
    for (const e of axEnds) e.style.opacity = P(t, T.hexA + 0.5, T.hexA + 0.9) * (1 - out);
    srcDeciles.style.opacity = P(t, T.hexA + 0.7, T.hexA + 1.1) * (1 - out);
  }

  const rc = env(t, T.famIn + 0.3, T.famIn + 0.7, T.logoA - 0.3, T.logoA);
  css(reformChip, { left: VERT ? W / 2 + "px" : W - 120 + "px", top: VERT ? 212 + "px" : 104 + "px", opacity: rc, transform: VERT ? "translateX(-50%)" : "translateX(-100%)" });
}


function scene6(t) {
  const lp = P(t, T.logoB - 0.15, T.logoB + 0.45, E.outCubic);
  const lh = M.logoH || 208;
  css(logoImg, {
    left: L.logo.cx - L.logo.w / 2 + "px", top: L.logo.cy - lh / 2 + "px", width: L.logo.w + "px",
    opacity: lp, filter: `blur(${lerp(6, 0, lp)}px) drop-shadow(0 0 ${lerp(30, 0, lp)}px rgba(79,209,197,0.6))`,
  });
  const tp = P(t, T.tag, T.tag + 0.6, E.outCubic);
  css(tagEl, { top: L.logo.cy + lh / 2 + 60 + "px", opacity: tp, transform: `translateY(${lerp(16, 0, tp)}px)` });
  const up = P(t, T.url, T.url + 0.6, E.outCubic);
  css(urlEl, { top: L.logo.cy + lh / 2 + 160 + "px", opacity: up, transform: `translateY(${lerp(12, 0, up)}px)` });
}

function grain(t) {
  const f = Math.round(t * 60);
  const rnd = mulberry32(f * 7919 + 13);
  const w = grainCv.width, h = grainCv.height;
  const img = grainCtx.createImageData(w, h);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 110 + rnd() * 36;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  grainCtx.putImageData(img, 0, 0);
  grainCv.style.opacity = 0.18;
}

function background(t) {
  // faint teal bloom that drifts with the story
  const a = 0.10 + 0.05 * Math.sin(t * 0.7);
  const gx = lerp(35, 65, t / DUR), gy = lerp(40, 55, t / DUR);
  stage.style.background = `radial-gradient(ellipse 80% 70% at ${gx}% ${gy}%, rgba(44,122,123,${a}) 0%, rgba(11,14,20,0) 60%), #0B0E14`;
}

// ------------------------------------------------------------------ render
function renderAt(t) {
  t = clamp(t, 0, DUR);
  background(t);
  scene1(t);
  scene2(t);
  scene3(t);
  drawDots(t);
  scene45(t);
  scene6(t);
  grain(t);
}

// --------------------------------------------------------------- audio cues
function buildEvents() {
  const ev = [];
  const push = (t, type, extra = {}) => ev.push({ t: +t.toFixed(4), type, ...extra });
  push(0, "pour", { dur: T.pourB });
  quoteWords.forEach((_, i) => push(T.quoteIn + i * T.qStag, "word", { i }));
  push(T.lawFocus - 0.7, "whoosh", { dur: 0.75 });
  push(T.zoomAmt, "lock");
  push(T.flyStart, "whoosh", { dur: T.flyEnd - T.flyStart });
  push(T.flyEnd, "land");
  codeLines.forEach((_, i) => push(T.codeIn + 0.15 + i * 0.032, "key", { i }));
  push(T.refIn, "ping", { note: 0 });
  reformLines.forEach((_, i) => push(T.reformIn + 0.1 + i * 0.06, "key", { i: i + 40 }));
  push(T.reformVal, "ping", { note: 4 });
  // the curve sonified: pitch follows the computed gain as the playhead draws it
  const cpts = V.household.curve.points;
  const samples = [];
  for (let k = 0; k <= 40; k++) {
    const u = k / 40, tt = lerp(T.curveA, T.curveB, u);
    const e = E.inOutSine(u) * V.household.curve.xMax;
    const g = cpts[Math.min(cpts.length - 1, Math.round(e / 250))][1];
    samples.push([+tt.toFixed(4), g]);
  }
  push(T.curveA, "curve", { samples, gmax: V.household.gain });
  push(T.line1, "ping", { note: 0 });
  push(T.riseA, "rise", { dur: T.riseB - T.riseA });
  push(T.line2, "hit");
  push(T.zoomA, "drop");
  // gainers light up in $800 steps; plinks rise in pitch with the step
  const bins = new Map();
  for (const d of dots) if (d.gain > 0.5) {
    const key = Math.round(d.lightT / 0.06) * 10 + d.step;
    bins.set(key, (bins.get(key) || 0) + 1);
  }
  for (const [key, n] of [...bins].sort((a, b) => a[0] - b[0])) push(Math.floor(key / 10) * 0.06, "plink", { n, step: key % 10 });
  V.nation.stats.forEach((_, i) => push([T.stat1, T.stat2, T.stat3][i], "stat", { i }));
  push(T.hexA, "whoosh", { dur: T.hexFill - T.hexA - 0.1 });
  const vmax = Math.max(...bars.map((b) => b.v));
  bars.forEach((b, i) => push(b.inT, "decile", { n: 3 + i, v: b.v / vmax }));
  push(T.logoA, "swell", { dur: T.logoB - T.logoA });
  push(T.logoB, "logo");
  EVENTS = ev.sort((a, b) => a.t - b.t);
}

// -------------------------------------------------------------------- boot
async function loadJSON(p) {
  try { const r = await fetch(p, { cache: "no-store" }); if (!r.ok) return null; return await r.json(); } catch { return null; }
}

function mockSample() {
  const rnd = mulberry32(99);
  const fips = [6, 48, 12, 36, 42, 17, 39, 13, 37, 26, 34, 51, 53, 4, 47, 18, 25, 29, 24, 55];
  return Array.from({ length: 12000 }, () => [fips[Math.floor(rnd() * fips.length)], rnd() < 0.3 ? 800 * (1 + Math.floor(rnd() * 3)) : 0, null]);
}

(async function boot() {
  const real = await loadJSON("/data/video.json");
  V = real || MOCK_VIDEO;
  if (!real) {
    V.sample = mockSample();
    V.code = V.code || (await loadJSON("/data/code_mock.json"));
    V.nation.caption = ["MOCK ", "caption"];
    V.nation.dotNote = "MOCK";
    V.signoff = "MOCK";
  }
  build();
  await document.fonts.ready;
  await Promise.all([...document.fonts].map((f) => f.load().catch(() => {})));
  await new Promise((r) => (logoImg.complete ? r() : (logoImg.onload = r)));
  measure();
  buildMap();
  buildDeciles();
  buildLogoPoints();
  makeSprites();
  buildEvents();
  window.renderAt = renderAt;
  window.getEvents = () => EVENTS;
  window.DUR = DUR;
  const tq = Q.get("t");
  if (Q.get("play")) {
    const t0 = performance.now() - (tq ? +tq * 1000 : 0);
    const loop = () => { renderAt(((performance.now() - t0) / 1000) % DUR); requestAnimationFrame(loop); };
    loop();
  } else renderAt(tq ? +tq : 0);
  window.__ready = true;
})();
