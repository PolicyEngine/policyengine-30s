// Draw data/uk/geography.json in headless Chromium with the d3-geo build the
// page uses, to eyeball the shapes, the winding and dot placement.
// The dots are MOCK: 20 uniform random points per constituency, not data.
//
// usage: node tools/uk/preview_uk_geography.mjs [out.png] [projection]
//   projection: conformal (site/main.js today, default) | tm | equalarea

import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const ROOT = new URL("../../", import.meta.url);
const out = process.argv[2] || "uk_geography_preview.png";
const which = process.argv[3] || "conformal";
const geo = readFileSync(new URL("data/uk/geography.json", ROOT), "utf8");
const d3src = readFileSync(new URL("node_modules/d3-geo/dist/d3-geo.min.js", ROOT), "utf8");
const d3arr = readFileSync(new URL("node_modules/d3-array/dist/d3-array.min.js", ROOT), "utf8");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.setContent(`<html><body style="margin:0;background:#0F172A"><canvas id=c width=1920 height=1080></canvas></body></html>`);
await page.addScriptTag({ content: d3arr });
await page.addScriptTag({ content: d3src });
const info = await page.evaluate(([G, which]) => {
  const g = JSON.parse(G);
  const feats = g.constituencies.map((d) => ({ type: "Feature", id: d.code, properties: d, geometry: { type: "MultiPolygon", coordinates: d.polys } }));
  const fc = { type: "FeatureCollection", features: feats };
  const make = {
    conformal: () => d3.geoConicConformal().parallels([50, 58]).rotate([2.5, 0]),
    tm: () => d3.geoTransverseMercator().rotate([2, 0]),
    equalarea: () => d3.geoConicEqualArea().parallels([50, 58]).rotate([2.5, 0]),
  }[which];
  const box = [[660, 60], [1800, 1040]]; // taller than the site's box so the shapes are legible
  const proj = make().fitExtent(box, fc);
  const path = d3.geoPath(proj);
  const ctx = document.getElementById("c").getContext("2d");
  const hue = { England: "#285E61", Wales: "#6B46C1", Scotland: "#2B6CB0", "Northern Ireland": "#B7791F" };
  let seed = 20260925;
  const rnd = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  let outside = 0, dots = 0;
  const dotXY = [];
  for (const f of feats) {
    const p2 = new Path2D(path(f));
    ctx.fillStyle = hue[f.properties.nation];
    ctx.fill(p2);
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.lineWidth = 0.5;
    ctx.stroke(p2);
    const [[x0, y0], [x1, y1]] = path.bounds(f);
    for (let k = 0; k < 20; k++) {
      let x, y, tries = 0;
      do { x = x0 + (x1 - x0) * rnd(); y = y0 + (y1 - y0) * rnd(); tries++; } while (!ctx.isPointInPath(p2, x, y) && tries < 400);
      dots++;
      if (!ctx.isPointInPath(p2, x, y)) outside++;
      dotXY.push([x, y]);
    }
  }
  ctx.fillStyle = "#B2F5EA";
  for (const [x, y] of dotXY) { ctx.beginPath(); ctx.arc(x, y, 0.9, 0, 2 * Math.PI); ctx.fill(); }
  ctx.fillStyle = "#F8FAFC";
  ctx.font = "600 28px sans-serif";
  ctx.fillText("PREVIEW - MOCK dots (20 random per constituency), not data", 40, 60);
  ctx.font = "20px sans-serif";
  ctx.fillText(`650 Westminster constituencies (July 2024), ONS BUC; projection: ${which}`, 40, 96);
  const legend = Object.entries(hue);
  legend.forEach(([n, c], i) => { ctx.fillStyle = c; ctx.fillRect(40, 130 + i * 34, 22, 22); ctx.fillStyle = "#F8FAFC"; ctx.fillText(n, 72, 149 + i * 34); });
  ctx.font = "16px sans-serif";
  g.meta.attribution.forEach((l, i) => ctx.fillText(l, 40, 1010 + i * 24));
  return { dots, outside, bounds: path.bounds(fc) };
}, [geo, which]);
await page.screenshot({ path: out });
await browser.close();
console.log(JSON.stringify({ out, projection: which, ...info }));
if (info.outside) process.exit(1);
