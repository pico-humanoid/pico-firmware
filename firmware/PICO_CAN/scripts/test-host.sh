#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# > 0 )); then echo "Usage: $0 (PICO_TEST_SANITIZERS=ON optional)" >&2; exit 2; fi
cmake -S "$root/tests" -B "$root/build/Host-Tests" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug -DPICO_TEST_SANITIZERS="${PICO_TEST_SANITIZERS:-OFF}"
cmake --build "$root/build/Host-Tests" --parallel 4
ctest --test-dir "$root/build/Host-Tests" --output-on-failure
