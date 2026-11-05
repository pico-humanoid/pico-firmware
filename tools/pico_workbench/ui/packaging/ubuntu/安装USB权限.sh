#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$0")" && pwd)"
if [[ $EUID -ne 0 ]]; then
  if command -v pkexec >/dev/null; then exec pkexec /bin/bash "$0"; fi
  exec sudo /bin/bash "$0"
fi
source_dir="$root/usb-permissions"
[[ -d "$source_dir" ]] || { echo '缺少随包 USB 规则目录。'; exit 2; }
backup="/var/backups/pico-usb-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$backup"
for file in "$source_dir"/*.rules; do
  name="${file##*/}"
  if [[ -f "/etc/udev/rules.d/$name" ]]; then cp -p "/etc/udev/rules.d/$name" "$backup/"; fi
  install -o root -g root -m 0644 "$file" "/etc/udev/rules.d/$name"
done
udevadm control --reload-rules
echo 'USB 规则已安装。请拔插开发板和 USB-CAN；若仍无权限，注销后重新登录。'
