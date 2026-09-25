"""Check every rendered deliverable: container specs, loudness, single-frame glitches.

A glitch is a frame that differs sharply from both neighbours while the
neighbours resemble each other (a pop, a flash, a one-frame layout jump).

usage: uv run --with numpy tools/check_outputs.py out/*.mp4
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import numpy as np


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels,pix_fmt",
         "-show_entries", "format=duration,size", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def loudness(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = err[err.rfind("Summary:"):]
    get = lambda k: float(re.search(rf"{k}:\s+(-?[\d.]+)", summary).group(1))
    return {"I_LUFS": get("I"), "LRA": get("LRA"), "true_peak_dBTP": get("Peak")}


def glitches(path, w=240):
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    h = round(int(v["height"]) * w / int(v["width"]) / 2) * 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))           # |f[i+1]-f[i]|
    skip = np.abs(f[2:] - f[:-2]).mean(axis=(1, 2))           # |f[i+1]-f[i-1]|
    fps = eval(v["r_frame_rate"])
    out = []
    for i in range(1, len(f) - 1):
        a, b = d[i - 1], d[i]
        if min(a, b) > 2.0 and min(a, b) > 3 * skip[i - 1]:
            out.append((round(i / fps, 3), round(float(min(a, b)), 2), round(float(skip[i - 1]), 2)))
    return len(f), out


def main(paths):
    ok = True
    for p in paths:
        info = probe(p)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
        dur = float(info["format"]["duration"])
        L = loudness(p)
        n, g = glitches(p)
        print(f"\n{p}\n  video {v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']} {v['pix_fmt']}  frames {n}  "
              f"duration {dur:.3f}s  size {int(info['format']['size']) / 1e6:.1f} MB")
        print(f"  audio {a['codec_name'] if a else 'NONE'} {a.get('sample_rate') if a else ''} Hz x{a.get('channels') if a else ''}  "
              f"{L['I_LUFS']} LUFS  LRA {L['LRA']}  true peak {L['true_peak_dBTP']} dBTP")
        print(f"  single-frame glitches: {len(g)}" + ("" if not g else f"  {g[:10]}"))
        if abs(dur - 30.0) > 0.05 or not a or L["true_peak_dBTP"] > -1.0 or abs(L["I_LUFS"] + 14) > 1.0 or g:
            ok = False
    print("\nALL CHECKS PASS" if ok else "\nCHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
