#!/usr/bin/env bash
# ホストで走るファームのテスト。Batch/NamzWire は Arduino に依存しないので
# 素の g++ でコンパイルできる（PlatformIO も実機も要らない）。
#
#   firmware/test/run.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../lib"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

g++ -std=gnu++17 -Wall -Wextra -Werror \
  -I "$LIB/Batch" -I "$LIB/NamzWire" \
  -o "$OUT/test_batch_bytes" \
  "$HERE/test_batch_bytes.cpp" "$LIB/Batch/Batch.cpp" "$LIB/NamzWire/NamzWire.cpp"

"$OUT/test_batch_bytes"
