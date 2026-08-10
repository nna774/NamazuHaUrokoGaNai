# テスト機で2号機と同じバッチ設定を再現するenvを追加した

## 背景

`docs/log/2026-08-11-device2-upgrade-concern.md`でPR #72（Batchプール枯渇
フォールバック撤去 + `pump()`のRAM優先化）を2号機へまだ焼かないと決めた際、
「テスト機で2号機と同じ`kBatchSeconds=15`・`kMaxRamBatches=3`設定の長時間
backlog試験から始める」という次のステップを残していた。これに着手する。

さっきインターネット不調時に2号機が再起動していたのも動機（今回の懸念が
実際に絡んでいるかは未確認、時系列が一致するだけ）。

## テスト機にADXL355は無い

テスト機（`tools/devices.json`の`id: 4294967295`）は`sensor: iis3dhhc`で
登録済みで、ADXL355は物理的に繋がっていない。実センサ無しで2号機のタイミング
だけ再現したい。

## 気付いたこと: FAKEとADXL355のifdefは独立に効く

`config.h`の`kBatchSeconds`・`kMaxRamBatches`と、`main.cpp`の
`kBatchRecordBytes`（レコードサイズ、ADXL355はint32で12B/サンプル）は
すべて`#ifdef NAMZ_SENSOR_ADXL355`だけで分岐する。一方`main.cpp`のセンサ
選択部は`#ifdef NAMZ_SENSOR_FAKE ... #elif defined(NAMZ_SENSOR_ADXL355)`と
いう`elif`チェーンで、FAKEが定義されていれば優先される。

つまり両方を同時に定義すれば「FakeSensorで駆動（実センサ不要）しつつ、
バッチ秒数・RAMキュー本数・レコードサイズは2号機と同一」というビルドが
既存の仕組みだけで作れる。新しいセンサコードもconfig.hの分岐も増やさず、
`platformio.ini`に新env`[env:fake-sensor-device2-profile]`
（`env:fake-sensor`を拡張し`-DNAMZ_SENSOR_ADXL355=1`を足すだけ）を追加した。

## 確認したこと

`pio run -e fake-sensor-device2-profile`でビルド成功。ELFに`kSensorName`の
文字列`"FAKE"`が入っている（ADXL355ではなくFakeSensorが選ばれている）ことと、
`compile_commands.json`で`main.cpp`に`-DNAMZ_SENSOR_FAKE`・
`-DNAMZ_SENSOR_ADXL355`が両方渡っていることを確認した。既存env
(`esp32dev`/`adxl355`/`fake-sensor`)のビルドと`firmware/test/run.sh`
（wireバイト等価・TlsMemPoolストレステスト）も通ることを確認済み。

## 次にやること

このenvをテスト機に焼き、spillに大量backlogを作った状態で長時間動かし、
`docs/log/2026-08-11-batch-pool-fallback-heap-corruption.md`で計測した
device1の指標（`batch-pool-exhausted`回数・`[sampling] newBatch stuck`
エピソード・DNS/POST失敗・heap_free/maxblock_8bit推移）と同じものを見る。
良さそうなら2号機へ展開する。
