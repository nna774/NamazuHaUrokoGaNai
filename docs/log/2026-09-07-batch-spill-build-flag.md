# 常時spill化(PR #184)をビルドフラグ化して既定無効にした

[PR #184](https://github.com/nna774/NamazuHaUrokoGaNai/pull/184)（常時spill化の
実験実装、[log/2026-08-30-batch-spill-before-send.md](2026-08-30-batch-spill-before-send.md)）が
「採用するか未確定」のままdraftで放置され続けていたのを、ユーザー指示で解消した。
採用判断待ちでPRを寝かせ続けるのではなく、コード自体は既定無効のビルドフラグで
mainに合流させ、実機での実測(flash摩耗・I/O負荷)をしたい時だけ有効化できる形にした。

## 変更

- `firmware/src/main.cpp`の`batchDrainTask`・`firmware/src/piezo_main.cpp`の
  `uploaderTask`に追加した`flushToSpill()`呼び出しを`#ifdef NAMZ_ALWAYS_SPILL`で
  囲んだ。未定義（既定）ならPR #184マージ前と完全に同じ挙動になる。
- `firmware/platformio.ini`に`esp32dev-always-spill`・`adxl355-always-spill`・
  `piezo-always-spill`の3envを追加した。`-DNAMZ_ALWAYS_SPILL=1`を足すだけで、
  他はbase env(`esp32dev`/`adxl355`/`piezo`)をそのまま継承する。本番機
  (device1/device2/device3)に直接焼いて実測できるようにする狙い——この機能は
  テスト機ではなく本番機のflash摩耗・I/O負荷を見たいものなので、既存の
  probe/test env群（`tls-alloc-probe`等）とは違い、本番envの直接拡張にした。
- `docs/design.md`の該当項を、ビルドフラグ化と既定無効である旨に更新した。

## 確認できていないこと

このworktreeにはPlatformIO(`pio`)がインストールされておらず、`firmware/test/run.sh`
（batch-uplinkのビルド成果物に依存）も含めてビルド確認ができなかった。変更は
`#ifdef`ガードの追加と`platformio.ini`への新規env追加のみで、変更前の3env
(`esp32dev`/`adxl355`/`piezo`)のビルド結果には影響しないはずだが、マージ前に
`pio run -e esp32dev -e adxl355 -e piezo`と`firmware/test/run.sh`を実行できる
環境で確認すること。
