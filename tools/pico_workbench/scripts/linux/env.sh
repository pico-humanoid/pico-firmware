#!/usr/bin/env bash
PICO_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -z "${PICO_TOOLS_ROOT:-}" ]]; then
  if [[ -d "$PICO_PROJECT_ROOT/../tools" ]]; then
    PICO_TOOLS_ROOT="$(cd "$PICO_PROJECT_ROOT/../tools" && pwd)"
  else
    PICO_TOOLS_ROOT="$(dirname -- "$(dirname -- "$PICO_PROJECT_ROOT")")/STM32Tools/ubuntu"
  fi
fi
export CUBE_BUNDLE_PATH="${CUBE_BUNDLE_PATH:-$PICO_TOOLS_ROOT/stm32cube/bundles}"
export CMSIS_PACK_ROOT="${CMSIS_PACK_ROOT:-$PICO_TOOLS_ROOT/stm32cube/packs}"
export PATH="$PICO_TOOLS_ROOT/bin:$CUBE_BUNDLE_PATH/gnu-tools-for-stm32/14.3.1+st.2/bin:$CUBE_BUNDLE_PATH/gnu-gdb-for-stm32/14.3.1+st.2/bin:$CUBE_BUNDLE_PATH/cmake/4.4.0+st.1/bin:$CUBE_BUNDLE_PATH/ninja/1.13.2+st.1/bin:$PATH"
export LD_LIBRARY_PATH="$PICO_TOOLS_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
PICO_PYTHON="$PICO_TOOLS_ROOT/python-env/bin/python"
export PICO_PROJECT_ROOT PICO_TOOLS_ROOT PICO_PYTHON
