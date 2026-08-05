# device2 の自宅回線断とspill容量の見積もり

device2（ADXL355機）が自宅インターネット不調でオフラインになり、自動復帰待ちの状態から
調査した。

## 何を決めたか

batch-uplink の `Uploader` に「spill(LittleFS退避)が満杯の時は古いデータから捨てる」
動作を**オプトインの引数**で追加する方針にした。デフォルトは現状維持（spillが満杯なら
RAMキューへ無制限に積み増す）とし、Electabuzz 側の挙動は変えない。Namazu の
`main.cpp` からは明示的にオプトインする。

## なぜそう決めたか

- 実容量を計算し直したところ、`firmware/src/config.h` の `kMaxSpillBatches = 20000`
  （コメント「90日ぶんの上限目安」）は物理パーティションと整合していないと分かった。
  `firmware/platformio.ini` は `board_build.partitions`/`flash_size` を指定しておらず、
  Arduino framework 既定の 4MB 用 `default.csv` が使われる。この表の `spiffs` パーティションは
  `0x160000`(約1.4MB)しかない。
  device2(ADXL355)は `kBatchSeconds=15`、1本 約18KB(1500サンプル×12B+ヘッダ)なので、
  spill満杯までは 1,441,792 / 18,432 ≈ 78本 × 15秒 ≈ **約19.5分**。20分の欠測はほぼ
  この上限ラインだった。
- 現行の `Uploader::enqueue()` は、spill(LittleFS)への退避が失敗すると
  RAMキューへ無制限に積み増す実装になっている（コード中のコメント
  「退避できなければ諦めて積む（メモリ許す範囲）」の通り、意図した挙動）。
  長時間の欠測が続くとヒープを食い潰してクラッシュしうる。
- ユーザーから「あふれるなら古いデータから消えるほうがいい」という優先順位が明示された。

## 却下した代替案

- **OTA用アプリ枠（`app1`）を削ってlittlefsに回す案は、今は採らない。**
  OTA は未実装（[docs/ota.md](../ota.md)）だが将来やる計画があり、OTA用の2アプリ枠は
  容量に余裕があれば残しておきたいとユーザーが明示したため。16MB確定後もこの方針は
  変えていない（後述の通り両方成立する容量があるので、削る理由自体が消えた）。
- **device1（`esp32dev` env）にも device2 と同じ16MB前提のパーティションを適用する案は、
  今は採らない。** device1の実チップ容量は今回まだ物理確認していない。TTGO T-Display系
  クローンは個体差があり、同じ型番でも同じ容量とは限らないため、`esp32dev` 共通部には
  手を出さず `adxl355` env（＝device2専用）だけに閉じて変更する。

## 発見された制約

- batch-uplink は Namazu と Electabuzz が共有している（[CLAUDE.md](../../CLAUDE.md)）。
  `Uploader` の挙動変更はデフォルト値を変えない形でしか入れられない。
- OTA未実装のため、パーティションテーブルの変更はファーム再ビルド＋物理再書き込みが要る。
  稼働中の device2 には次に現物を触れるタイミングでしか反映できない（リモートでは直せない）。
- フラッシュ容量は個体ごとに実測が要る。**esp32dev既定=4MBという思い込みは、device2の
  実チップでは外れていた**（後述）。同型番のクローンでも device1 が同じとは限らない。

## 新たに確認できた事実

- 公開の読み取り専用API `https://api.namazu.dark-kuins.net/devices` は
  `age_s`(最終受信からの経過秒)・`lag_s`(実時刻とのずれ秒)・`online` を返す。
  今回の欠測中に確認したところ `age_s≈469`・`lag_s≈1657`・`online=false` で、
  完全な無音ではなく断続的に接続していた（8分前に一度部分送信できていた）ことが分かった。
- device1(IIS3DHHC, int16, 30秒/バッチ)と device2(ADXL355, int32, 15秒/バッチ)は
  バッチサイズがどちらも約18KB/本に揃うよう `kBatchSeconds` が調整済み
  （`firmware/src/config.h` のコメント参照）。
- **device2の実機を `esptool.py flash_id` で物理確認した。ESP32-D0WDQ6 v1.1、
  Manufacturer 85 / Device 2018、Detected flash size = 16MB**（MAC `5c:01:3b:07:b3:f8`）。
  想定していた既定4MBの4倍あり、littlefs領域を大きく確保してもOTA用の2アプリ枠を
  削らずに済む容量があると分かった。
- 現在のファームのビルドサイズは約994KB（4MB版パーティションでFlash使用21.6%）。
  最初は framework 既定の `large_spiffs_16MB.csv`（app0/app1 各4.5MB）で試して
  ビルドが通ることを確認したが、994KBのビルドに4.5MB枠は過大と分かり、
  `firmware/partitions_adxl355_16mb.csv`（app0/app1 各2MB＝現状の約2倍の余裕、
  spiffs 約11.88MB）へ**切り替えた**。この構成でも `pio run -e adxl355` は成功する
  （Flash使用48.6%）。spill満杯までは 12,451,840 / 18,432 ≈ 675本 × 15秒 ≈
  **約168.8分（約2時間49分）**まで伸びる（現状の4MB前提・約19.5分から約8.7倍）。
  この変更は `adxl355` env にのみ適用する。

## 次に何が可能になったか

batch-uplink 側での実装（spill満杯時に古いデータから捨てるオプトイン動作）と、
Namazu側でのdevice2向けパーティション拡張（16MB・`large_spiffs_16MB`ベース）の
両方に着手できる。Namazu 側の `firmware/platformio.ini` のタグpinと
`terraform/build_lambda.sh` の `UPLINK_VERSION` は、batch-uplink 側のPRがマージされ
タグが切られてから追従する。

**TODO: device1（`esp32dev` env）も同じボードのはずなので、いずれ現物を
`esptool.py --port <port> flash_id` で物理確認する。** 16MBだった場合は、
device2と同じ `firmware/partitions_adxl355_16mb.csv` 相当の拡張パーティション
（`large_spiffs_16MB`ベース）を焼き直す時に当てられる（ファイル名は
device1用に切り出すか汎用名にリネームするか、その時に判断する）。
