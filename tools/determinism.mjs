// Every frame must depend only on t: a fresh page asked for time t has to match,
// pixel for pixel, a page that played the film up to t. Streaming workers start
// mid-film, so any state left over from earlier frames would show up here.
import { chromium } from "playwright";
import { serve } from "./serve.mjs";

const [W, H] = (process.argv[2] || "1920x1080").split("x").map(Number);
const times = [2.5, 4.4, 6.9, 9.6, 12.4, 14.3, 17.2, 20.7, 23.3, 25.4, 29.5];
const server = await serve(0);
const url = `http://127.0.0.1:${server.address().port}/site/index.html?w=${W}&h=${H}`;
const browser = await chromium.launch();
const open = async () => {
  const p = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 0.5 });
  await p.goto(url);
  await p.waitForFunction(() => window.__ready === true);
  return p;
};
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
  if (!same) fails++;
  console.log(`t=${t}s  ${same ? "identical" : "DIFFERS"}`);
  t0 = t;
}
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
