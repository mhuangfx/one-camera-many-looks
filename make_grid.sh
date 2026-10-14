#!/usr/bin/env bash
# 3x3 grid of nine renders (each scaled to 640x360 -> 1920x1080), 10 s, no sound.
# Usage: make_grid.sh out.mp4 look1.mp4 ... look9.mp4   (reading order: left to right, top to bottom)
set -euo pipefail
out="$1"; shift
[ "$#" -eq 9 ] || { echo "need 9 input videos"; exit 1; }
in=(); f=""
for i in $(seq 0 8); do
  in+=(-i "${@:$((i+1)):1}")
  f+="[$i:v]scale=640:360,setsar=1,trim=0:10,setpts=PTS-STARTPTS[v$i];"
done
f+="[v0][v1][v2][v3][v4][v5][v6][v7][v8]xstack=inputs=9:layout=0_0|w0_0|w0+w1_0|0_h0|w0_h0|w0+w1_h0|0_h0+h3|w0_h0+h3|w0+w1_h0+h3[out]"
ffmpeg -nostdin -y -loglevel error "${in[@]}" -filter_complex "$f" -map "[out]" -an \
  -c:v libx264 -crf 18 -pix_fmt yuv420p "$out" && echo "$out"
