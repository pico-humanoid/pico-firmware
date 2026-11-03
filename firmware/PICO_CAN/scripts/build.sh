#!/usr/bin/env bash
# Linux builds use separate directories; archived Windows images are untouched.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
usage() {
    echo "Usage: $0 [Loopback|External|BMS-Read-500K|Power-Read-1M|Power-Read-500K|Dual-Read-500K|Power-Baud-1M-to-500K|Power-Baud-500K-to-1M|Devices|All]"
    echo 'Set PICO_BUILD_JOBS to override the default parallelism (4).'
}
if (( $# > 1 )); then usage >&2; exit 2; fi
case "${1:-Loopback}" in
    Loopback|External|BMS-Read-500K|Power-Read-1M|Power-Read-500K|Dual-Read-500K|Power-Baud-1M-to-500K|Power-Baud-500K-to-1M) modes=("${1:-Loopback}") ;;
    Devices) modes=(BMS-Read-500K Power-Read-1M Power-Read-500K Dual-Read-500K) ;;
    All) modes=(Loopback External BMS-Read-500K Power-Read-1M Power-Read-500K Dual-Read-500K) ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
jobs="${PICO_BUILD_JOBS:-4}"
if [[ ! "$jobs" =~ ^[1-9][0-9]*$ ]]; then
    echo 'PICO_BUILD_JOBS must be a positive integer.' >&2
    exit 2
fi
if [[ "$(uname -s)" != Linux ]]; then
    echo 'This entry point requires Linux. Windows users should use build.ps1.' >&2
    exit 2
fi
for tool in cmake ninja arm-none-eabi-gcc arm-none-eabi-objcopy; do
    if ! command -v "$tool" >/dev/null; then
        echo "Missing required tool: $tool" >&2
        exit 1
    fi
done
cd -- "$project_root"
for mode in "${modes[@]}"; do
    cmake --preset "Linux-$mode"
    cmake --build --preset "Linux-$mode" --parallel "$jobs"
done
