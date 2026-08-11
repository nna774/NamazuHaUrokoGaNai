# ピエゾ実験機、phase1（クラウド統合）を実装した

[docs/piezo.md §7](../piezo.md#7-phase1クラウド統合の設計方針)で決めた設計方針を
実装した。Lambda側3箇所・firmware側は新規`[env:piezo]`まで到達。**実機の書き込み・
動作確認はまだ**（コードはビルド確認のみ）。

## Lambda側: 設計方針通り3コミットで収まった

- `lambda/common/wire.py`: `SENSOR_TYPE_PIEZO=128`、`is_calibrated(sensor_type)`
  （`128〜249`のみFalse、`255`のFAKEはTrue扱い）、`parse()`の`axes!=3`ガードを
  撤廃して`axes`可変（`reshape(count, axes)`）に。
- `lambda/detect/handler.py`: `_process()`冒頭に`wire.is_calibrated()`ガード1行。
  設計時の見立て通り、これだけで震度計算を丸ごとスキップできた。
- `lambda/api/handler.py`: `_waveform_payload()`の手前に`_pad_to_3ch()`を追加し、
  axes<3のgalをy,z列0埋めで3列に揃えた。`dashboard/app.js`は無改修。

`.venv/bin/python -m pytest lambda/tests`で135件全通過。

## firmware側: 「本線への統合」が「別ファイル+タスクモデルの作り直し」に変わった

設計時点(§7)では「`docs/piezo_phase0/`は育てず本線`firmware/`配下の`[env:]`として
統合する」としていたが、実装に入って**ESP32-C3スーパーミニがシングルコア
（RISC-V単コア）**であることを再確認し、方針を修正した。本線`main.cpp`は
「Core1=測定(100Hz)・Core0=送信/WiFi/TLS」というデュアルコア分離が前提
（[docs/design.md](../design.md)「ESP32ボードの差し替え」に明記済みだったが、
設計段階では見落としていた）。シングルコアでは「単なる設定変更ではない」ため、
`main.cpp`を直接拡張するのではなく、`piezo_main.cpp`という別エントリポイントを
新設した（`provision_main.cpp`等と同じ、`build_src_filter`で`main.cpp`と排他する
既存パターンに乗せた）。

- **測定タスク・送信タスクの2タスク構成**: シングルコアでもFreeRTOSの複数タスクは
  作れる（プリエンプティブなタイムスライス）。`xTaskCreatePinnedToCore`ではなく
  `xTaskCreate`（コア指定なし）を使い、キュー経由で連携する設計にした。将来
  デュアルコア機に載せる場合は`xTaskCreatePinnedToCore`に変えてコアを指定する
  だけで済む見込み（逆方向のシングルコア化より簡単なはず、という判断）。
- **スピル・自動リトライは追加実装不要**: `Uploader`（batch-uplink）は
  「2xxが返るまでバッチを捨てない」不変条件を持ち、`spillDir`を渡すだけで
  LittleFSへの自動退避、`pump()`だけで送信リトライ・バックオフが完結する。
  本線が独自に実装している部分ではなく標準機能だった。
- **OTA・複雑な信頼性機構は今回見送り**: 本線のOTA(pull型)・電源断からの
  多段階復旧は移植しなかった。ただし送信タスクに差し込み口(コメント)だけ残し、
  後で足しやすくした。
- **RAM不足への警戒**: 本線(IIS3DHHC機)は実機で`kMaxRamBatches=2`(36KB)でも
  一般ヒープが断片化しDNS解決が繰り返し失敗する事象を踏んでいる
  （520KB SRAM機でこれ）。ピエゾは1軸int16(2B/サンプル)で本線の1/3の
  データ量だが、TLSハンドシェイクのオーバーヘッド自体は軸数と無関係。
  ESP32-C3はSRAM総量も本線より少ない。保守的に`kMaxRamBatches=1`から
  始め、起動時に空きヒープをログへ出す（本線と同じ方針）。実機で確認
  しないと分からない、というのはユーザーとも合意済み。
- **`AccelSensor`は継承しない**: `x,y,z`3軸gal前提が型に埋め込まれているため。
  代わりに`RawSensor`という非校正・N軸センサ用の抽象を新設し、`PiezoSensor`
  （GPIO4のADCを読むだけ）で実装した。将来コンタクトマイク等が増えても
  差し替えられる。
- **`NamzWire`のN軸対応**: `sampleBytes`/`newBatch`/`fillHeader`に`axes`引数
  （既定値3、本線の呼び出しは無変更）を追加、N軸版の`addSampleN`を新設した。

## ビルド確認で見つけた回帰

`[env:esp32dev]`の`build_src_filter`（`main.cpp`と排他するファイルの除外リスト）に
`piezo_main.cpp`を足し忘れ、本線ビルドが`setup()`/`loop()`の二重定義でリンクエラーに
なった。修正して本線(`esp32dev`)・`adxl355`・`sensortest`・`provision`・
`firmware/test/run.sh`（golden test）を再確認し、回帰が無いことを確認した。
`extends`で`build_src_filter`を継承するenv（`sensortest`/`fake-sensor`/`adxl355`等）は
親(`esp32dev`)の修正だけで自動的にカバーされ、`build_src_filter`を丸ごと
上書きするenv（`provision`/`*-probe`系）はそもそも`piezo_main.cpp`を意識する
必要が無いことも実際にビルドして確認した。

## 次に可能になったこと

コードはここまで。残りは実機作業:

1. `python tools/provision_device.py add --id N --sensor piezo` でdevice_id払い出し
2. `tools/provision_device.py tfvars` → `terraform/terraform.tfvars`に貼って
   `terraform apply`（サーバ側を先に登録、順序厳守）
3. `python tools/provision_device.py provision-h --id N` → `pio run -e piezo-provision`
4. `pio run -e piezo -t upload` → 実機で送信確認
5. S3への格納・dashboardでの波形表示確認、RAM/ヒープの実測
