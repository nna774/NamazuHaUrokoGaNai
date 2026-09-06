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
- `.github/workflows/firmware-build.yml`のビルドマトリクスに3envを追加した。
  秘密や実機を要らず本番envに定義を1つ足すだけなので、probe/provision系(対象外)
  ではなく本番3系統と同列に含めた。

## 確認したこと

作業したworktreeにはPlatformIO(`pio`)がインストールされておらずローカルではビルド
確認できなかったが、このPRブランチをmasterへ追従させたタイミングで
`firmware-build`/`firmware-host-test`CI（2026-09-02にmasterへ追加されていたもの、
[log/2026-09-02-firmware-build-ci.md](2026-09-02-firmware-build-ci.md)）が初めて
このブランチにも効くようになり、`esp32dev`/`adxl355`/`piezo`/`fake-sensor`/
`fake-sensor-device2-profile`は全green（`test`ジョブ=`firmware/test/run.sh`も
green）で確認できた。追加した3つの`-always-spill`envは同じCIワークフローに
追加した直後の最新pushでまだ結果待ち——PRのCIチェックで確認すること。
