#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
mode="${1:-Loopback}"
case "$mode" in Loopback|External) ;; *) echo '用法：flash.sh Loopback|External [ST-LINK序列号]' >&2; exit 2 ;; esac
image="$PICO_PROJECT_ROOT/build/Ubuntu-$mode/PICO_CAN.elf"
programmer="$CUBE_BUNDLE_PATH/programmer/2.23.0/bin/STM32_Programmer_CLI"
if [[ ! -f "$image" ]]; then echo "没有 $mode 固件，请先编译。" >&2; exit 2; fi
probes="$({ "$programmer" -l st-link || true; } 2>&1)"
printf '%s\n' "$probes"
mapfile -t serials < <(printf '%s\n' "$probes" | sed -nE 's/.*ST-LINK SN[[:space:]]*:[[:space:]]*([^[:space:]]+).*/\1/p')
if (( ${#serials[@]} == 0 )); then
  echo '未识别到 ST-LINK。连接开发板的 ST-LINK USB；若已连接，检查 USB 权限和数据线。' >&2; exit 2
fi
if [[ -n "${2:-}" ]]; then
  serial="$2"
  printf '%s\n' "${serials[@]}" | grep -Fxq -- "$serial" || { echo '指定的 ST-LINK 未连接。' >&2; exit 2; }
elif (( ${#serials[@]} == 1 )); then serial="${serials[0]}"
else echo '检测到多个 ST-LINK，请在第二个参数指定序列号。' >&2; exit 2
fi
"$programmer" -c port=SWD freq=1000 "sn=$serial" -w "$image" -v -rst
