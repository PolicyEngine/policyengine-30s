"""Timed contact sheets from rendered frames: sheets.py <frames_dir> <fps> <out_prefix> [step_s] [thumb_w]"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

d, fps, out = Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
step = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
tw = int(sys.argv[5]) if len(sys.argv) > 5 else 640
frames = sorted(d.glob("f*.png"))
times = [i * step for i in range(int(len(frames) / fps / step))]
per = 12
for s in range(0, len(times), per):
    chunk = times[s : s + per]
    thumbs = []
    for t in chunk:
        im = Image.open(frames[min(len(frames) - 1, round(t * fps))]).convert("RGB")
        im = im.resize((tw, round(im.height * tw / im.width)))
        ImageDraw.Draw(im).rectangle([0, 0, 78, 26], fill=(0, 0, 0))
        ImageDraw.Draw(im).text((6, 6), f"{t:5.1f}s", fill=(255, 220, 0))
        thumbs.append(im)
    th = thumbs[0].height
    cols = 3
    sheet = Image.new("RGB", (cols * tw, ((len(thumbs) + cols - 1) // cols) * th))
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(f"{out}_{s // per}.png")
    print(f"{out}_{s // per}.png", chunk[0], chunk[-1])
