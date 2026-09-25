// Render every frame with headless Chromium, then hand off to ffmpeg.
// usage: node tools/render.mjs [--w 1920 --h 1080 --fps 60 --scale 2 --workers 8 --from 0 --to 30 --out frames/landscape --stills 0,4.5,12]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { serve } from "./serve.mjs";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((a, v, i, arr) => (v.startsWith("--") ? [...a, [v.slice(2), arr[i + 1]]] : a), [])
);
const W = +(args.w || 1920), H = +(args.h || 1080), FPS = +(args.fps || 60);
const SCALE = +(args.scale || 2), WORKERS = +(args.workers || 8);
const FROM = +(args.from || 0), TO = +(args.to || 30);
const OUT = path.resolve(args.out || "frames/landscape");
fs.mkdirSync(OUT, { recursive: true });

const server = await serve(0);
const port = server.address().port;
const browser = await chromium.launch({ args: ["--force-color-profile=srgb", "--font-render-hinting=none"] });
const pageUrl = `http://127.0.0.1:${port}/site/index.html?w=${W}&h=${H}`;

async function newPage() {
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: SCALE });
  page.on("pageerror", (e) => console.error("pageerror:", e.message));
  await page.goto(pageUrl);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 60000 });
  return page;
}

if (args.stills) {
  const page = await newPage();
  for (const s of args.stills.split(",")) {
    const t = +s;
    await page.evaluate((t) => window.renderAt(t), t);
    await page.screenshot({ path: path.join(OUT, `still_${t.toFixed(2)}.png`) });
  }
  if (args.events) fs.writeFileSync(args.events, JSON.stringify(await page.evaluate(() => window.getEvents()), null, 0));
  await browser.close(); server.close();
  process.exit(0);
}

if (args.stream) {
  // Stream mode: each worker owns a contiguous frame range and pipes PNGs
  // straight into its own ffmpeg encoder, so no frames touch the disk.
  // Segments share encoder settings and are joined with stream copy.
  const outFile = path.resolve(args.stream);
  const segDir = outFile + ".segments";
  fs.mkdirSync(segDir, { recursive: true });
  const nFrames = Math.round((TO - FROM) * FPS);
  const per = Math.ceil(nFrames / WORKERS);
  const vf = args.vf || "null";
  const crf = args.crf || "16";
  const t0 = Date.now();
  let done = 0;
  const segs = [];
  async function segWorker(k) {
    const a = k * per, b = Math.min(nFrames, a + per);
    if (a >= b) return;
    const seg = path.join(segDir, `seg${String(k).padStart(2, "0")}.mp4`);
    segs[k] = seg;
    const ff = spawn("ffmpeg", ["-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-",
      "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", crf, "-pix_fmt", "yuv420p", "-profile:v", "high",
      "-x264-params", "keyint=" + FPS + ":min-keyint=1", "-movflags", "+faststart", seg], { stdio: ["pipe", "inherit", "inherit"] });
    const closed = new Promise((res, rej) => ff.on("close", (c) => (c === 0 ? res() : rej(new Error("ffmpeg exit " + c)))));
    const page = await newPage();
    for (let f = a; f < b; f++) {
      await page.evaluate((t) => window.renderAt(t), FROM + f / FPS);
      const buf = await page.screenshot({ type: "png" });
      if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
      if (++done % 120 === 0) process.stdout.write(`\r${done}/${nFrames} frames  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    ff.stdin.end();
    await closed;
    await page.close();
  }
  await Promise.all(Array.from({ length: WORKERS }, (_, k) => segWorker(k)));
  const list = path.join(segDir, "list.txt");
  fs.writeFileSync(list, segs.filter(Boolean).map((s) => `file '${s}'`).join("\n"));
  const evPage = await newPage();
  fs.writeFileSync(outFile.replace(/\.mp4$/, ".events.json"), JSON.stringify(await evPage.evaluate(() => window.getEvents())));
  const muxArgs = ["-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", list];
  if (args.audio) muxArgs.push("-i", path.resolve(args.audio), "-c:a", "aac", "-b:a", "320k", "-shortest");
  muxArgs.push("-c:v", "copy", "-movflags", "+faststart", outFile);
  await new Promise((res, rej) => spawn("ffmpeg", muxArgs, { stdio: "inherit" }).on("close", (c) => (c === 0 ? res() : rej(new Error("mux " + c)))));
  fs.rmSync(segDir, { recursive: true, force: true });
  console.log(`\nstreamed ${nFrames} frames in ${((Date.now() - t0) / 1000).toFixed(0)}s -> ${outFile}`);
  await browser.close(); server.close();
  process.exit(0);
}

const frames = [];
for (let f = Math.round(FROM * FPS); f < Math.round(TO * FPS); f++) frames.push(f);
let next = 0, done = 0;
const t0 = Date.now();
async function worker() {
  const page = await newPage();
  while (next < frames.length) {
    const f = frames[next++];
    const file = path.join(OUT, `f${String(f).padStart(5, "0")}.png`);
    await page.evaluate((t) => window.renderAt(t), f / FPS);
    await page.screenshot({ path: file });
    if (++done % 60 === 0) process.stdout.write(`\r${done}/${frames.length} frames  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
}
await Promise.all(Array.from({ length: WORKERS }, worker));
const evPage = await newPage();
fs.writeFileSync(path.join(OUT, "events.json"), JSON.stringify(await evPage.evaluate(() => window.getEvents())));
console.log(`\nrendered ${frames.length} frames in ${((Date.now() - t0) / 1000).toFixed(0)}s -> ${OUT}`);
await browser.close();
server.close();
