#!/usr/bin/env bash
# 各Lambda関数のzipを terraform/builds/<fn>.zip に生成する。
# handler.py + common/ + jismo/ を集め、numpy を同梱する。
# terraform apply の前に実行すること。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
LAMBDA="$REPO/lambda"
JISMO="$REPO/tools/jismo"
BUILD="$HERE/builds"

PY="${PYTHON:-python3}"

rm -rf "$BUILD"
mkdir -p "$BUILD"

build_one() {
  fn="$1"
  stage="$BUILD/$fn"
  mkdir -p "$stage"
  cp "$LAMBDA/$fn/handler.py" "$stage/handler.py"
  cp -r "$LAMBDA/common" "$stage/common"
  cp -r "$JISMO" "$stage/jismo"
  # numpy を同梱（Lambda実行環境向け manylinux）
  "$PY" -m pip install --quiet \
    --platform manylinux2014_x86_64 --only-binary=:all: \
    --target "$stage" numpy >/dev/null
  # __pycache__ 除去
  find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
  (cd "$stage" && zip -qr "$BUILD/$fn.zip" .)
  echo "built $BUILD/$fn.zip"
}

for fn in ingest detect api; do
  build_one "$fn"
done
