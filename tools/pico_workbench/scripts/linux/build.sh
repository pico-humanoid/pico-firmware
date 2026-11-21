#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
# Use the same experiment catalogue/tool detection as the desktop, not machine-specific presets.
ui_dir="$PICO_PROJECT_ROOT/ui"
if [[ "${1:-Loopback}" == All ]]; then
  "$PICO_PYTHON" "$ui_dir/build_selected.py" Loopback
  "$PICO_PYTHON" "$ui_dir/build_selected.py" External
else
  "$PICO_PYTHON" "$ui_dir/build_selected.py" "${1:-Loopback}"
fi
