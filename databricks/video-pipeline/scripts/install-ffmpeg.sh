#!/usr/bin/env bash
set -euo pipefail

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  ffmpeg -version | head -n 1
  ffprobe -version | head -n 1
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get is required to install ffmpeg on this Databricks cluster image" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends ffmpeg

ffmpeg -version | head -n 1
ffprobe -version | head -n 1
