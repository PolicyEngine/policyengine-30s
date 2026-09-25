#!/bin/sh
# Final deliverables: 4K/60 master, 1080p/60 downscale, 9:16 supersampled from 2x, posters.
set -e
cd "$(dirname "$0")/.."
node tools/render.mjs --w 1920 --h 1080 --fps 60 --scale 2 --workers 10 --crf 16 \
  --stream out/policyengine-30s-4k60.mp4 --audio audio/score.wav
ffmpeg -loglevel error -y -i out/policyengine-30s-4k60.mp4 -vf scale=1920:1080:flags=lanczos \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -profile:v high -c:a copy -movflags +faststart \
  out/policyengine-30s-1080p60.mp4
node tools/render.mjs --w 1080 --h 1920 --fps 60 --scale 2 --workers 10 --crf 17 \
  --vf scale=1080:1920:flags=lanczos \
  --stream out/policyengine-30s-vertical-1080x1920.mp4 --audio audio/score.wav
node tools/render.mjs --w 1920 --h 1080 --scale 2 --stills 12.9,18.9,23.6,28.8 --out out/posters-16x9
node tools/render.mjs --w 1080 --h 1920 --scale 2 --stills 12.9,18.9,23.6,28.8 --out out/posters-9x16
echo ALL-DONE
