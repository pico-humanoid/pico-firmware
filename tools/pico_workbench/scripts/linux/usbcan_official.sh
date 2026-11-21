#!/usr/bin/env bash
# Run the unmodified Waveshare Windows GUI in an isolated 64-bit Wine prefix.
# System packages are installed only when missing, through local sudo authentication.
set -euo pipefail

source "$(dirname -- "$0")/env.sh"
project_dir="$PICO_PROJECT_ROOT"
source_dir="${PICO_USBCAN_VENDOR_SOURCE:-$project_dir/tools/usbcan-official/USBCANV2.12_Chinese}"
app_dir="$project_dir/tools/usbcan-official/USBCANV2.12_Chinese"
prefix_dir="${XDG_DATA_HOME:-$HOME/.local/share}/pico-usbcan-official/wine64"
serial_id="${PICO_USBCAN_PORT:-/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0}"

if [[ ${1:-} == --check ]]; then
  printf '官方程序：%s\nWine：%s\n独立环境：%s\n串口：%s\n' \
    "$app_dir/USBCANV2.12.exe" "$(command -v wine || true)" "$prefix_dir" "$serial_id"
  [[ -f "$app_dir/USBCANV2.12.exe" ]] && echo '程序文件已就绪。'
  if [[ -r "$serial_id" && -w "$serial_id" ]]; then
    echo 'USB-CAN 串口可读写。'
  else
    echo 'USB-CAN 未连接或当前用户缺少串口访问权限。'
  fi
  exit 0
fi

mkdir -p "$project_dir/logs"
run_log="$project_dir/logs/usbcan-official-$(TZ=Asia/Shanghai date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$run_log") 2>&1
on_error() {
  local result=$?
  trap - ERR
  printf '\n启动失败（退出码 %s），日志保存在：%s\n' "$result" "$run_log"
  if [[ -t 0 ]]; then read -r -p '按回车关闭此终端。' _reply || true; fi
  exit "$result"
}
trap on_error ERR

if [[ ! -x /usr/lib/wine/wine64 || ! -x /usr/bin/wine ]]; then
  echo '可选的 Windows 官方工具需要 Wine；请自行安装 wine/wine64，或使用原生控制台。' >&2
  exit 2
fi

if [[ ! -f "$app_dir/USBCANV2.12.exe" ]]; then
  [[ -f "$source_dir/USBCANV2.12.exe" ]] || { echo "未提供厂商 Windows 工具；可设置 PICO_USBCAN_VENDOR_SOURCE，或使用原生控制台。" >&2; exit 2; }
  mkdir -p "$app_dir"
  cp -a "$source_dir/." "$app_dir/"
fi

export WINEPREFIX="$prefix_dir"
export WINEARCH=win64
export WINEDEBUG=-all
# This Qt program uses neither .NET nor embedded HTML; skip unrelated runtime prompts.
export WINEDLLOVERRIDES='mscoree,mshtml=;winemenubuilder.exe=d'
mkdir -p "$WINEPREFIX"
if [[ ! -f "$WINEPREFIX/system.reg" ]]; then
  echo '正在首次初始化独立的 Wine 环境，请稍候。'
  /usr/lib/wine/wine64 wineboot -i
  /usr/bin/wineserver -w
fi

serial_port="$serial_id"
if [[ ! -e "$serial_port" && -e /dev/ttyUSB0 ]]; then serial_port=/dev/ttyUSB0; fi
if [[ ! -r "$serial_port" || ! -w "$serial_port" ]]; then
  echo '未找到可读写的 USB-CAN 串口。请先接上 USB-CAN，再重新运行此入口。'
  (exit 2)
fi

mkdir -p "$WINEPREFIX/dosdevices"
ln -sfn "$serial_port" "$WINEPREFIX/dosdevices/com1"
/usr/lib/wine/wine64 reg add 'HKLM\Software\Wine\Ports' /v COM1 /t REG_SZ /d "$serial_port" /f
/usr/lib/wine/wine64 reg add 'HKLM\HARDWARE\DEVICEMAP\SERIALCOMM' \
  /v '\Device\PicoUSBSerial0' /t REG_SZ /d COM1 /f

python3 - "$app_dir/cfg.txt" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
backup = path.with_name('cfg-before-pico-ubuntu.txt')
if path.exists() and not backup.exists():
    backup.write_bytes(path.read_bytes())
    text = path.read_text(encoding='utf-8-sig')
    fields = text.split(',')
    if len(fields) >= 10:
        fields[0:4] = ['2000000', '正常模式', '扩展帧', '1M']
        fields[8:10] = ['00000000', '00000000']
        path.write_text(','.join(fields), encoding='utf-8')
PY

echo '官方上位机即将打开。选择 COM1、串口 2000000、CAN 1M、正常模式、扩展帧。'
echo '滤波 ID / 屏蔽 ID 均为 00000000，再点击“打开”和“设置并启动”。'
echo '本入口只打开上位机，不自动发送 CAN 报文或写入开发板。'
echo "运行日志：$run_log"
cd "$app_dir"
/usr/lib/wine/wine64 "$app_dir/USBCANV2.12.exe"
