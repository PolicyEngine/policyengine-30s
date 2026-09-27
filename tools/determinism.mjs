// Every frame must depend only on t: a fresh page asked for time t has to match a
// page that played the film up to t. Streaming workers start mid-film, so any state
// left over from earlier frames would show up here.
//
// Match means byte-identical, with one allowance: Chromium's software rasterizer can
// round a blurred glow slightly differently when it repaints only the damaged part of
// a page (the played-through one) than when it paints the page whole (the fresh one).
// On Linux CI that leaves a few dozen pixels in the curve's glow off by a few levels.
// So a frame also passes, reported as "within noise", when no channel of any pixel
// differs by more than NOISE_LEVELS and under NOISE_SHARE of pixels differ at all. A
// real leftover state (a moved element, a wrong opacity) moves far more than that.
import fs from "node:fs";
import { chromium } from "playwright";
import { serve } from "./serve.mjs";

const [W, H] = (process.argv[2] || "1920x1080").split("x").map(Number);
const NOISE_LEVELS = 8;      // of 255, per channel
const NOISE_SHARE = 0.0005;  // of the frame's pixels
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
// decode both screenshots in a blank page and compare them pixel by pixel
const cmpPage = await browser.newPage();
const compare = (a, b) => cmpPage.evaluate(async ([a, b]) => {
  const load = async (src) => { const i = new Image(); i.src = src; await i.decode(); return i; };
  const [ia, ib] = await Promise.all([load(a), load(b)]);
  const px = (img) => {
    const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
    const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(img, 0, 0);
    return g.getImageData(0, 0, img.width, img.height).data;
  };
  const da = px(ia), db = px(ib);
  let differing = 0, worst = 0;
  for (let i = 0; i < da.length; i += 4) {
    const m = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2]), Math.abs(da[i + 3] - db[i + 3]));
    if (m) { differing++; worst = Math.max(worst, m); }
  }
  return { differing, worst, share: differing / (da.length / 4) };
}, ["data:image/png;base64," + a.toString("base64"), "data:image/png;base64," + b.toString("base64")]);
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
  const same = Buffer.compare(a, b) === 0;
  const d = same ? null : await compare(a, b);
  const noise = d && d.worst <= NOISE_LEVELS && d.share < NOISE_SHARE;
  if (!same && !noise) {
    // keep both frames so a failure on another machine (CI) can be inspected
    fails++;
    fs.mkdirSync("frames/determinism", { recursive: true });
    const tag = `${W}x${H}-${country}-t${t}`;
    fs.writeFileSync(`frames/determinism/${tag}-played.png`, a);
    fs.writeFileSync(`frames/determinism/${tag}-fresh.png`, b);
  }
  console.log(`t=${t}s  ${same ? "identical" : noise ? `within noise (${d.differing} px, at most ${d.worst} levels)` : `DIFFERS (${d.differing} px, up to ${d.worst} levels)`}`);
  t0 = t;
}
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
