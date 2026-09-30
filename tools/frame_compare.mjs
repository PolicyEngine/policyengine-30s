// Compare two PNG screenshots pixel by pixel in a blank Chromium page (no image dependency).
//
// A match is byte-identical, with one allowance: Chromium's software rasterizer can round a
// blurred glow slightly differently between a partial and a full repaint, and on Linux CI that
// leaves a few dozen pixels a few levels off. A frame passes as "within noise" when no channel
// of any pixel differs by more than NOISE_LEVELS and under NOISE_SHARE of pixels differ at all.
// A real difference (a moved element, a wrong size or opacity) moves far more than that.
export const NOISE_LEVELS = 8;      // of 255, per channel
export const NOISE_SHARE = 0.0005;  // of the frame's pixels

export async function comparer(browser) {
  const page = await browser.newPage();
  return async (a, b) => {
    if (Buffer.compare(a, b) === 0) return { same: true, noise: false, differing: 0, worst: 0, share: 0 };
    const d = await page.evaluate(async ([a, b]) => {
      const load = async (src) => { const i = new Image(); i.src = src; await i.decode(); return i; };
      const [ia, ib] = await Promise.all([load(a), load(b)]);
      if (ia.width !== ib.width || ia.height !== ib.height) return { differing: Infinity, worst: 255, share: 1 };
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
    return { same: false, noise: d.worst <= NOISE_LEVELS && d.share < NOISE_SHARE, ...d };
  };
}

export const describe = (d) => d.same ? "identical"
  : d.noise ? `within noise (${d.differing} px, at most ${d.worst} levels)`
  : `DIFFERS (${d.differing} px, up to ${d.worst} levels)`;
