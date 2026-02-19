#!/usr/bin/env bash
# Quick build + upload for component dev. Plug in Nano and run:
#   ./upload.sh
set -e
cd "$(dirname "$0")"
PIO="pio"
command -v pio >/dev/null 2>&1 || PIO="$HOME/.platformio/penv/bin/pio"
$PIO run -e component_dev -t upload
