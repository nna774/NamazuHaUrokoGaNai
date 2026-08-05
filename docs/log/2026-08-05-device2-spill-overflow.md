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

- **OTA用アプリ枠（`app1`, 1.25MB）を削ってlittlefsに回す案は、今は採らない。**
  OTA は未実装（[docs/ota.md](../ota.md)）だが将来やる計画があり、OTA用の2アプリ枠は
  容量に余裕があれば残しておきたいとユーザーが明示したため。
- **実フラッシュチップがesp32dev既定の4MBより大きい前提でのパーティション拡張は、今は着手しない。**
  TTGO T-Display系クローンは4MB以外の容量の個体も流通しており、実容量は
  `esptool.py --port <port> flash_id` で物理確認しないと分からない。誤って大きい値を
  宣言すると起動が壊れるため、確認できるまでは踏み込まない。

## 発見された制約

- batch-uplink は Namazu と Electabuzz が共有している（[CLAUDE.md](../../CLAUDE.md)）。
  `Uploader` の挙動変更はデフォルト値を変えない形でしか入れられない。
- OTA未実装のため、パーティションテーブルの変更はファーム再ビルド＋物理再書き込みが要る。
  稼働中の device2 には次に現物を触れるタイミングでしか反映できない（リモートでは直せない）。

## 新たに確認できた事実

- 公開の読み取り専用API `https://api.namazu.dark-kuins.net/devices` は
  `age_s`(最終受信からの経過秒)・`lag_s`(実時刻とのずれ秒)・`online` を返す。
  今回の欠測中に確認したところ `age_s≈469`・`lag_s≈1657`・`online=false` で、
  完全な無音ではなく断続的に接続していた（8分前に一度部分送信できていた）ことが分かった。
- device1(IIS3DHHC, int16, 30秒/バッチ)と device2(ADXL355, int32, 15秒/バッチ)は
  バッチサイズがどちらも約18KB/本に揃うよう `kBatchSeconds` が調整済み
  （`firmware/src/config.h` のコメント参照）。

## 次に何が可能になったか

batch-uplink 側での実装に着手できる。Namazu 側の `firmware/platformio.ini` のタグpinと
`terraform/build_lambda.sh` の `UPLINK_VERSION` は、batch-uplink 側のPRがマージされ
タグが切られてから追従する。
