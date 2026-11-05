#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
cd -- "$PICO_PROJECT_ROOT"
mode="${1:-Loopback}"
case "$mode" in
  Loopback|External) modes=("$mode") ;;
  All) modes=(Loopback External) ;;
  *) echo '用法：build.sh Loopback|External|All' >&2; exit 2 ;;
esac
cmake_exe="$CUBE_BUNDLE_PATH/cmake/4.4.0+st.1/bin/cmake"
for item in "${modes[@]}"; do
  "$cmake_exe" --preset "Ubuntu-$item"
  "$cmake_exe" --build --preset "Ubuntu-$item" --parallel 4
done
