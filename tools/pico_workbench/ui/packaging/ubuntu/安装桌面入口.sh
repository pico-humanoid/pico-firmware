#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$0")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps"
for pair in 'PICOConsole:PICO 开发控制台' 'PICOLogViewer:PICO 日志查看器'; do
  exe="${pair%%:*}"; label="${pair#*:}"
  # Desktop Exec uses its own quoting rules, not shell expansion.
  escaped="${root//\\/\\\\}"; escaped="${escaped//\"/\\\"}"
  printf '[Desktop Entry]\nType=Application\nName=%s\nExec="%s/%s"\nPath=%s\nTerminal=false\nCategories=Development;\n' "$label" "$escaped" "$exe" "$root" > "$apps/pico-$exe.desktop"
  chmod 755 "$apps/pico-$exe.desktop"
done
printf '已添加到应用程序菜单。移动整个目录后，请重新运行本脚本更新入口。\n'
