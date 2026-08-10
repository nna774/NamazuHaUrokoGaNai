#!/usr/bin/env bash
# ホストで走るファームのテスト。Batch/NamzWire は Arduino に依存しないので
# 素の g++ でコンパイルできる（実機は要らない）。
#
#   firmware/test/run.sh
#
# Batch は batch-uplink（外部ライブラリ）側にあるので、PlatformIO が展開した
# 実体を使う。pin しているタグの中身をそのまま試すことになるので、
# 「手元のコピーは通るが実際に焼かれるものは違う」という食い違いが起きない。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="$HERE/../lib"
DEPS="$HERE/../.pio/libdeps"

UPLINK="$(find "$DEPS" -maxdepth 2 -type d -name 'batch-uplink' 2>/dev/null | head -1)"
if [ -z "$UPLINK" ]; then
  echo "batch-uplink が展開されていない。先に一度ビルドしろ:" >&2
  echo "  cd firmware && ../.venv/bin/pio run -e esp32dev" >&2
  exit 1
fi

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

g++ -std=gnu++17 -Wall -Wextra -Werror \
  -I "$UPLINK/src" -I "$LIB/NamzWire" \
  -o "$OUT/test_batch_bytes" \
  "$HERE/test_batch_bytes.cpp" "$UPLINK/src/Batch.cpp" "$LIB/NamzWire/NamzWire.cpp"

echo "batch-uplink: $(basename "$(dirname "$UPLINK")")/$(basename "$UPLINK")"
"$OUT/test_batch_bytes"

# TlsMemPoolCore は Arduino/mbedTLS 非依存の純粋なポインタ演算部分なので、
# 同じくホストのg++でコンパイルできる(TlsMemPool.cppはこれの薄いアダプタ)。
g++ -std=gnu++17 -Wall -Wextra -Werror \
  -I "$LIB/TlsMemPool" \
  -o "$OUT/test_tls_mem_pool" \
  "$HERE/test_tls_mem_pool.cpp" "$LIB/TlsMemPool/TlsMemPoolCore.cpp"

"$OUT/test_tls_mem_pool"
