#!/usr/bin/env bash
set -euo pipefail
ui_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(dirname -- "$ui_dir")"
if [[ -x "$project_dir/../PICOConsole" ]]; then
  exec "$project_dir/../PICOConsole" "$@"
fi
tools_root="$(printenv PICO_TOOLS_ROOT || true)"
if [[ -z "$tools_root" ]]; then tools_root="$(dirname -- "$(dirname -- "$project_dir")")/STM32Tools/ubuntu"; fi
if [[ -x "$tools_root/python-env/bin/python" ]]; then
  python_exe="$tools_root/python-env/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_exe="$(command -v python3)"
else
  printf '未找到 Python 3。请使用已准备的 Ubuntu 开发环境。\n' >&2
  exit 1
fi
# Keep startup/import/display failures visible rather than reporting false success.
exec "$python_exe" "$ui_dir/native.py" "$@"
