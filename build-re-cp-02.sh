#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# RAM type/timing remains a board assumption until checked on hardware.
export BOARD_PROFILE=${BOARD_PROFILE:-jdcloud-re-cp-02-tf}
exec bash ./customize.sh NOR '256k(u-boot),64k(u-boot-env),256k(factory),-(firmware)' \
  0x90000 18 7 880 1200 DDR3-256MiB 115200
