// Every frame must depend only on t: a fresh page asked for time t has to match a
// page that played the film up to t. Streaming workers start mid-film, so any state
// left over from earlier frames would show up here.
//
// Match means byte-identical, or within the rasterizer noise tools/frame_compare.mjs allows.
import fs from "node:fs";
import { chromium } from "playwright";
import { serve } from "./serve.mjs";
import { comparer, describe } from "./frame_compare.mjs";

const [W, H] = (process.argv[2] || "1920x1080").split("x").map(Number);
const times = [2.5, 4.4, 6.9, 9.6, 12.4, 14.3, 17.2, 20.7, 23.3, 25.4, 29.5];
const server = await serve(0);
const country = process.argv[3] || "us";
const url = `http://127.0.0.1:${server.address().port}/site/index.html?w=${W}&h=${H}&country=${country}`;
const browser = await chromium.launch();
const open = async () => {
  const p = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 0.5 });
  await p.goto(url);
  await p.waitForFunction(() => window.__ready === true);
  return p;
};
const compare = await comparer(browser);
const played = await open();
let fails = 0, t0 = 0;
for (const t of times) {
  for (let f = Math.round(t0 * 30); f < Math.round(t * 30); f += 3) await played.evaluate((x) => window.renderAt(x), f / 30);
  await played.evaluate((x) => window.renderAt(x), t);
  const a = await played.screenshot();
  const fresh = await open();
  await fresh.evaluate((x) => window.renderAt(x), t);
  const b = await fresh.screenshot();
  await fresh.close();
  const d = await compare(a, b);
  if (!d.same && !d.noise) {
    // keep both frames so a failure on another machine (CI) can be inspected
    fails++;
    fs.mkdirSync("frames/determinism", { recursive: true });
    const tag = `${W}x${H}-${country}-t${t}`;
    fs.writeFileSync(`frames/determinism/${tag}-played.png`, a);
    fs.writeFileSync(`frames/determinism/${tag}-fresh.png`, b);
  }
  console.log(`t=${t}s  ${describe(d)}`);
  t0 = t;
}
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
