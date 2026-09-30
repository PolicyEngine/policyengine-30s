// Does a change leave a film untouched? Render the same film from this checkout and from
// another (usually the PR's base), frame by frame, and compare them. The determinism check
// compares a revision with itself, so only this catches an unintended change to, say, the
// US film from work on the UK one.
//
// usage: node tools/compare_revisions.mjs <other-checkout> [country=us] [layouts=1920x1080,1080x1920] [step=0.2]
// Both checkouts need site/bundle.js built. Exits 1 if any frame differs beyond rasterizer noise.
import path from "node:path";
import { chromium } from "playwright";
import { serve } from "./serve.mjs";
import { comparer, describe } from "./frame_compare.mjs";

const [other, country = "us", layouts = "1920x1080,1080x1920", stepArg = "0.2"] = process.argv.slice(2);
if (!other) { console.error("usage: node tools/compare_revisions.mjs <other-checkout> [country] [layouts] [step]"); process.exit(2); }
const step = +stepArg;
const mine = await serve(0), theirs = await serve(0, path.resolve(other));
const browser = await chromium.launch();
const compare = await comparer(browser);
let fails = 0, noisy = 0, n = 0;
for (const layout of layouts.split(",")) {
  const [W, H] = layout.split("x").map(Number);
  const open = async (server) => {
    const p = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 0.5 });
    await p.goto(`http://127.0.0.1:${server.address().port}/site/index.html?w=${W}&h=${H}&country=${country}`);
    await p.waitForFunction(() => window.__ready === true);
    return p;
  };
  const [a, b] = [await open(mine), await open(theirs)];
  for (let k = 0; k * step <= 30 + 1e-9; k++) {
    const t = +(k * step).toFixed(3);
    await a.evaluate((x) => window.renderAt(x), t);
    await b.evaluate((x) => window.renderAt(x), t);
    const d = await compare(await a.screenshot(), await b.screenshot());
    n++;
    if (!d.same && !d.noise) fails++;
    if (d.noise) noisy++;
    if (!d.same) console.log(`${layout} t=${t}s  ${describe(d)}`);
  }
  await a.close(); await b.close();
}
console.log(`${country}: ${n} frames compared, ${n - fails - noisy} identical, ${noisy} within noise, ${fails} different`);
await browser.close(); mine.close(); theirs.close();
process.exit(fails ? 1 : 0);
