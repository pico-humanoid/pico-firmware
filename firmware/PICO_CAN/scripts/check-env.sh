#!/usr/bin/env bash
# Non-destructive Linux environment check: no hardware access or flashing.
set -euo pipefail
if (( $# )); then
    echo "Usage: $0" >&2
    exit 2
fi
failures=0
check_command() {
    if command -v "$1" >/dev/null; then
        printf '[OK] %-24s %s\n' "$1" "$(command -v "$1")"
    else
        printf '[MISSING] %s\n' "$1" >&2
        failures=$((failures + 1))
    fi
}
for tool in cmake ninja make gcc g++ arm-none-eabi-gcc arm-none-eabi-g++ \
    arm-none-eabi-objcopy arm-none-eabi-size gdb-multiarch python3 \
    openocd st-info st-flash st-util candump cansend clangd clang-format; do
    check_command "$tool"
done
if command -v python3 >/dev/null; then
    if ! python3 - <<'PY'
import importlib
import sys
failed = False
for name in ('serial', 'pytest'):
    try:
        mod = importlib.import_module(name)
        print(f'[OK] Python {name}: {getattr(mod, "__version__", "unknown")}')
    except ImportError as error:
        print(f'[MISSING] Python {name}: {error}', file=sys.stderr)
        failed = True
sys.exit(1 if failed else 0)
PY
    then failures=$((failures + 1)); fi
fi
if command -v gdb-multiarch >/dev/null; then
    if ! gdb-multiarch -nx -q -batch -ex 'set architecture arm' -ex 'show architecture'; then
        failures=$((failures + 1))
    fi
fi
if command -v openocd >/dev/null; then
    echo 'Checking STM32G4 configuration parsing only (no probe initialization)...'
    if ! openocd -c noinit -f interface/stlink.cfg -f target/stm32g4x.cfg -c shutdown; then
        failures=$((failures + 1))
    fi
fi
printf '\nHardware/USB permissions, actual flashing and live CAN are NOT tested.\n'
printf 'Missing or failed checks: %s\n' "$failures"
if (( failures )); then exit 1; fi
