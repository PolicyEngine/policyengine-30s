// Check data/uk/geography.json the way the page will use it: d3-geo shapes,
// fitExtent into the map box of each layout, and the rejection sampling that
// places dots (site/main.js buildMap: up to 400 tries per dot, then the last
// try is kept whether or not it landed inside).
//
// usage: bun tools/uk/check_uk_geography.mjs     (writes data/uk/geography_check.json)

import { readFileSync, writeFileSync } from "node:fs";
import {
  geoArea, geoBounds, geoPath, geoConicConformal, geoConicEqualArea, geoTransverseMercator, geoMercator,
} from "d3-geo";

const ROOT = new URL("../../", import.meta.url);
const G = JSON.parse(readFileSync(new URL("data/uk/geography.json", ROOT), "utf8"));
const D3_GEO = JSON.parse(readFileSync(new URL("node_modules/d3-geo/package.json", ROOT), "utf8")).version;
const R_KM = 6371.0088; // mean Earth radius; d3's geoArea is in steradians on the unit sphere
const [X0, Y0, X1, Y1] = G.meta.validation.bbox_limit;
const TRIES = 400; // site/main.js buildMap

let failures = 0;
const fail = (msg) => { failures++; console.error("FAIL", msg); };

const feats = G.constituencies.map((d) => ({
  type: "Feature", id: d.code, properties: { name: d.name, nation: d.nation, region: d.region },
  geometry: { type: "MultiPolygon", coordinates: d.polys },
}));
const fc = { type: "FeatureCollection", features: feats };

// ------------------------------------------------ winding and extent on the sphere
if (feats.length !== 650) fail(`expected 650 constituencies, got ${feats.length}`);
if (new Set(feats.map((f) => f.id)).size !== feats.length) fail("duplicate codes");
const areaKm2 = new Map();
for (const f of feats) {
  const a = geoArea(f) * R_KM ** 2;
  areaKm2.set(f.id, a);
  // a ring wound the wrong way makes d3 read "the globe minus the constituency" (~5.1e8 km2)
  if (!(a > 0.5 && a < 20000)) fail(`${f.id} ${f.properties.name}: spherical area ${a.toFixed(1)} km2 (winding?)`);
  const [[lo0, la0], [lo1, la1]] = geoBounds(f);
  if (lo0 < X0 || lo1 > X1 || la0 < Y0 || la1 > Y1) fail(`${f.id} bounds ${[lo0, la0, lo1, la1]} outside UK box`);
}
const totalKm2 = [...areaKm2.values()].reduce((s, v) => s + v, 0);
const byNationKm2 = {};
for (const f of feats) byNationKm2[f.properties.nation] = (byNationKm2[f.properties.nation] || 0) + areaKm2.get(f.id);
const pythonKept = Object.fromEntries(Object.entries(G.meta.simplification.area_km2_by_nation).map(([n, v]) => [n, v.kept]));

// ------------------------------------------------ projections x layouts
// map boxes from site/main.js layout() (stage px; the 4K master renders the same stage at 2x)
const LAYOUTS = {
  "landscape 1920x1080": [[660, 290], [1800, 960]],
  "portrait 1080x1920": [[72, 560], [1008, 1160]],
};
const PROJECTIONS = {
  "geoConicConformal().parallels([50, 58]).rotate([2.5, 0])": () => geoConicConformal().parallels([50, 58]).rotate([2.5, 0]),
  "geoTransverseMercator().rotate([2, 0])": () => geoTransverseMercator().rotate([2, 0]),
  "geoConicEqualArea().parallels([50, 58]).rotate([2.5, 0])": () => geoConicEqualArea().parallels([50, 58]).rotate([2.5, 0]),
  "geoMercator()": () => geoMercator(),
};
// Shetland (north of 59.45N; Orkney's northernmost isles end near 59.4N) is one
// part of the Orkney and Shetland constituency; measure what an inset would buy
const noShetland = {
  type: "FeatureCollection",
  features: feats.map((f) => ({
    ...f,
    geometry: { type: "MultiPolygon", coordinates: f.geometry.coordinates.filter((poly) => !poly[0].every(([, lat]) => lat > 59.45)) },
  })),
};

const median = (v) => { const s = [...v].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
const r = (x, k = 3) => Math.round(x * 10 ** k) / 10 ** k;

const results = {};
for (const [pname, make] of Object.entries(PROJECTIONS)) {
  results[pname] = {};
  for (const [lname, box] of Object.entries(LAYOUTS)) {
    const proj = make().fitExtent(box, fc);
    const path = geoPath(proj);
    const [[bx0, by0], [bx1, by1]] = path.bounds(fc);
    const eps = 1e-6;
    if (bx0 < box[0][0] - eps || by0 < box[0][1] - eps || bx1 > box[1][0] + eps || by1 > box[1][1] + eps)
      fail(`${pname} ${lname}: bounds ${[bx0, by0, bx1, by1]} spill outside ${box}`);
    const boxW = box[1][0] - box[0][0], boxH = box[1][1] - box[0][1];
    const w = bx1 - bx0, h = by1 - by0;
    // area scale per constituency (px2 per km2), normalised by the median: 1.0 everywhere = equal-area
    const scale = [], fill = [], px = [];
    let empty = 0;
    for (const f of feats) {
      const d = path(f);
      if (!d) { empty++; continue; }
      const a = path.area(f);
      const [[fx0, fy0], [fx1, fy1]] = path.bounds(f);
      scale.push(a / areaKm2.get(f.id));
      const fr = a / ((fx1 - fx0) * (fy1 - fy0));
      fill.push({ code: f.id, name: f.properties.name, fill: fr, p_miss: (1 - fr) ** TRIES });
      px.push({ code: f.id, name: f.properties.name, px2: a });
    }
    if (empty) fail(`${pname} ${lname}: ${empty} constituencies project to nothing`);
    const m = median(scale);
    const s2 = scale.map((v) => v / m);
    fill.sort((a, b) => a.fill - b.fill);
    px.sort((a, b) => a.px2 - b.px2);
    const inset = make().fitExtent(box, noShetland);
    results[pname][lname] = {
      box,
      used_px: [r(w, 1), r(h, 1)],
      binding: Math.abs(w - boxW) < 1e-3 ? "width" : "height",
      km_per_stage_px_median: r(1 / Math.sqrt(m), 3),
      area_scale_min_max_vs_median: [r(Math.min(...s2), 4), r(Math.max(...s2), 4)],
      smallest_constituencies_stage_px2: px.slice(0, 3).map((x) => ({ ...x, px2: r(x.px2, 1) })),
      lowest_bbox_fill: fill.slice(0, 5).map((x) => ({ ...x, fill: r(x.fill, 4), p_miss: Number(x.p_miss.toPrecision(3)) })),
      constituencies_with_p_miss_over_1e6: fill.filter((x) => x.p_miss > 1e-6).length,
      scale_gain_if_shetland_inset: r(inset.scale() / proj.scale(), 3),
    };
  }
}

const out = {
  meta: {
    script: "tools/uk/check_uk_geography.mjs",
    d3_geo: D3_GEO,
    input: "data/uk/geography.json",
    notes: [
      "used_px: projected width and height of all 650 constituencies after fitExtent into the layout's map box (stage px; the 4K master is the same stage at 2x).",
      "area_scale_min_max_vs_median: projected area per km2 of each constituency divided by the median; a dot-density map reads fairly when this is close to 1 everywhere.",
      `lowest_bbox_fill: constituency area over its projected bounding box; p_miss = (1 - fill)^${TRIES}, the chance that one dot's ${TRIES} rejection-sampling tries all miss, in which case site/main.js keeps the last try, which is outside the shape.`,
    ],
  },
  sphere: {
    total_km2: r(totalKm2, 1),
    by_nation_km2: Object.fromEntries(Object.entries(byNationKm2).map(([k, v]) => [k, r(v, 1)])),
    python_geodesic_kept_km2: pythonKept,
    note: "d3 geoArea on a sphere of radius 6371.0088 km vs pyproj's WGS84 ellipsoid in the build script",
  },
  projections: results,
  failures,
};
writeFileSync(new URL("data/uk/geography_check.json", ROOT), JSON.stringify(out, null, 1) + "\n");
console.log(JSON.stringify(out.sphere));
for (const [p, v] of Object.entries(results))
  for (const [l, x] of Object.entries(v))
    console.log(`${p} | ${l} | used ${x.used_px} (${x.binding}) | ${x.km_per_stage_px_median} km/px | area scale ${x.area_scale_min_max_vs_median} | worst fill ${x.lowest_bbox_fill[0].name} ${x.lowest_bbox_fill[0].fill} p_miss ${x.lowest_bbox_fill[0].p_miss} | Shetland inset x${x.scale_gain_if_shetland_inset}`);
console.log(failures ? `${failures} FAILURES` : "all checks passed");
process.exit(failures ? 1 : 0);
