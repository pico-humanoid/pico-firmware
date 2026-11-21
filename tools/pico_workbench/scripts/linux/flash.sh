#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
exec "$PICO_PYTHON" "$PICO_PROJECT_ROOT/ui/flash_selected.py" "$@"
