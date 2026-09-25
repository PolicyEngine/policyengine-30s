#!/bin/sh
# Final deliverables for one country: 4K/60 master, 1080p/60 downscale, 9:16 supersampled from 2x, posters.
# usage: tools/render_all.sh [us|uk]   (US files keep their original names in out/; other countries go to out/<country>/)
set -e
cd "$(dirname "$0")/.."
C=${1:-us}
if [ "$C" = us ]; then O=out; N=policyengine-30s; A=audio/score.wav; else O=out/$C; N=policyengine-30s-$C; A=audio/$C/score.wav; fi
mkdir -p "$O"
node tools/render.mjs --country "$C" --w 1920 --h 1080 --fps 60 --scale 2 --workers 10 --crf 16 \
  --stream "$O/$N-4k60.mp4" --audio "$A"
ffmpeg -loglevel error -y -i "$O/$N-4k60.mp4" -vf scale=1920:1080:flags=lanczos \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -profile:v high -c:a copy -movflags +faststart \
  "$O/$N-1080p60.mp4"
node tools/render.mjs --country "$C" --w 1080 --h 1920 --fps 60 --scale 2 --workers 10 --crf 17 \
  --vf scale=1080:1920:flags=lanczos \
  --stream "$O/$N-vertical-1080x1920.mp4" --audio "$A"
node tools/render.mjs --country "$C" --w 1920 --h 1080 --scale 2 --stills 12.9,18.9,23.6,28.8 --out "$O/posters-16x9"
node tools/render.mjs --country "$C" --w 1080 --h 1920 --scale 2 --stills 12.9,18.9,23.6,28.8 --out "$O/posters-9x16"
echo ALL-DONE
