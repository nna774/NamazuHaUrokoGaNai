# device2 の自宅回線断とspill容量の見積もり

device2（ADXL355機）が自宅インターネット不調でオフラインになり、自動復帰待ちの状態から
調査した。

## 何を決めたか

batch-uplink の `Uploader` に「spill(LittleFS退避)が満杯の時は古いデータから捨てる」
動作を**オプトインの引数**で追加する方針にした。デフォルトは現状維持（spillが満杯なら
RAMキューへ無制限に積み増す）とし、Electabuzz 側の挙動は変えない。Namazu の
`main.cpp` からは明示的にオプトインする。

**device2は16MBフラッシュ全体を使うパーティション構成に書き換え、実機での正常動作
（起動・WiFi接続・ingestへの送信再開）まで確認済み。** spill満杯までの実容量は
約19.5分→**約168.8分（約2時間49分）**まで伸びた。

## なぜそう決めたか

- 実容量を計算し直したところ、`firmware/src/config.h` の `kMaxSpillBatches = 20000`
  （コメント「90日ぶんの上限目安」）は物理パーティションと整合していないと分かった。
  変更前の `firmware/platformio.ini` は `board_build.partitions` を指定しておらず、
  Arduino framework 既定の 4MB 用 `default.csv` が使われていた。この表の `spiffs`
  パーティションは `0x160000`(約1.4MB)しかない。
  device2(ADXL355)は `kBatchSeconds=15`、1本 約18KB(1500サンプル×12B+ヘッダ)なので、
  spill満杯までは 1,441,792 / 18,432 ≈ 78本 × 15秒 ≈ **約19.5分**。20分の欠測はほぼ
  この上限ラインだった。
- 現行の `Uploader::enqueue()` は、spill(LittleFS)への退避が失敗すると
  RAMキューへ無制限に積み増す実装になっている（コード中のコメント
  「退避できなければ諦めて積む（メモリ許す範囲）」の通り、意図した挙動）。
  長時間の欠測が続くとヒープを食い潰してクラッシュしうる。
- ユーザーから「あふれるなら古いデータから消えるほうがいい」という優先順位が明示された。
- `esptool.py flash_id` で device2 の実機を物理確認したところ、実際は **16MB**
  フラッシュだった（後述）。1.4MBしか無いという前提そのものが誤りだったので、
  容量問題は「切り詰める」より先に「正しく使う」余地があった。

## 却下した代替案

- **OTA用アプリ枠（`app1`）を削ってlittlefsに回す案は、今は採らない。**
  OTA は未実装（[docs/ota.md](../ota.md)）だが将来やる計画があり、OTA用の2アプリ枠は
  容量に余裕があれば残しておきたいとユーザーが明示したため。16MB化後もこの方針は
  変えていない（両方成立する容量があるので、削る理由自体が消えた）。
- **device1（`esp32dev` env）にも device2 と同じ16MB前提のパーティションを適用する案は、
  今は採らない。** device1の実チップ容量は今回まだ物理確認していない。TTGO T-Display系
  クローンは個体差があり、同じ型番でも同じ容量とは限らないため、`esp32dev` 共通部には
  手を出さず `adxl355` env（＝device2専用）だけに閉じて変更する。

## 発見された制約

- batch-uplink は Namazu と Electabuzz が共有している（[CLAUDE.md](../../CLAUDE.md)）。
  `Uploader` の挙動変更はデフォルト値を変えない形でしか入れられない。
- OTA未実装のため、パーティションテーブルの変更はファーム再ビルド＋物理再書き込みが要る。
  device2への反映も、現物を手元に持ってきてUSB接続する形で行った（リモートでは直せない）。
- フラッシュ容量は個体ごとに実測が要る。**esp32dev既定=4MBという思い込みは、device2の
  実チップでは外れていた**。同型番のクローンでも device1 が同じとは限らない。
- **PlatformIO(espressif32プラットフォーム)でフラッシュサイズを上書きするキーは
  `board_build.flash_size` ではなく `board_upload.flash_size`。** ビルドスクリプト
  （`~/.platformio/platforms/espressif32/builder/main.py`）は `board.get("upload.flash_size", ...)`
  を読んでおり、`board_build.flash_size` は存在しないキーとして黙って無視される。
  この思い違いにハマった経緯は「注意が必要な難所」を参照。

## 注意が必要な難所

- **`board_build.flash_size` は静かに無視される、booby trap的な設定キー。**
  最初 `board_build.partitions`（16MB用パーティション表）と `board_build.flash_size = 16MB`
  を両方指定してビルド・書き込みしたところ、`pio run` はエラーなく成功したにも関わらず
  実機はROMブートローダのバナー直後（`entry 0x400805e4`）から一切先に進まず、
  約27ms周期でリセットを繰り返した（12秒間に439回、2nd stageブートローダの
  ログすら1行も出ない）。`flash_mode`をdio/doutどちらに変えても同一症状、
  `esptool.py erase_flash` で全消去してから焼き直しても同一症状、8MBでも同一症状で、
  「4MBなら動く／8MB以上は起動しない」ようにしか見えなかった。
  `pio run -e adxl355 -t upload -v` で実際のesptoolコマンド列を確認して初めて、
  `elf2image`/`write_flash` のどちらも **`--flash_size 4MB` のまま**（16MB指定が
  一切反映されていない）と分かった。**パーティション表（csv）だけは16MB分の
  オフセットで作られたまま、イメージヘッダとesptoolの書き込みは4MBのフラッシュだと
  思い込んでいた**、という不整合が実際の原因だった。`board_upload.flash_size = 16MB`
  に直したところ、`-v` の出力で全ての `--flash_size` が16MBに揃い、実機も一発で
  正常起動した。
- **同じ症状でも原因は1つとは限らない。** 「4MBは動く・8MBと16MBは動かない」という
  観測結果だけを見ると「16MBは対応外」のような結論に飛びつきそうになるが、実際は
  「4MB」がこのボード定義の既定値（＝`board_upload.flash_size`を指定しなかった時の
  フォールバック）とたまたま一致していただけで、フラッシュサイズの大小とは無関係
  だった。設定を疑う時は、ビルドツールが**実際に何を実行しているか**（`-v` 相当の
  出力）を先に見るべきだった。

## 新たに確認できた事実

- 公開の読み取り専用API `https://api.namazu.dark-kuins.net/devices`（`/devices/<id>` も可）は
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
- 現在のファームのビルドサイズは約994KB。framework 既定の `large_spiffs_16MB.csv`
  （app0/app1 各4.5MB）はこのビルドサイズに対して過大と判断し、
  `firmware/partitions_adxl355_16mb.csv`（app0/app1 各2MB＝現状の約2倍の余裕、
  spiffs 約11.88MB）を自作して採用した。
- **最終的に `board_upload.flash_size = 16MB` + 自作パーティション表で、実機が
  正常起動しWiFi接続・ingestへの送信再開まで確認できた**
  （2026-08-05、`age_s≈9秒`・`lag_s≈25秒`・`online=true`）。
  spill満杯までは 12,451,840 / 18,432 ≈ 675本 × 15秒 ≈ **約168.8分（約2時間49分）**。

## 次に何が可能になったか

device2は16MB全体を使うパーティション構成の実機で運用に復帰済み。batch-uplink側の
実装（spill満杯時に古いデータから捨てるオプトイン動作）はこのまま進められる
（マージ・タグ切り後、`firmware/platformio.ini` の `lib_deps` タグと
`terraform/build_lambda.sh` の `UPLINK_VERSION` を揃えて追従し、`main.cpp` の
`Uploader` 生成に `dropOldestWhenFull=true` を渡す）。

**TODO: device1（`esp32dev` env）も同じボードのはずなので、いずれ現物を
`esptool.py --port <port> flash_id` で物理確認する。** 16MBだった場合、今回
`board_upload.flash_size` の落とし穴も解決済みなので、`partitions_adxl355_16mb.csv`
相当の拡張パーティションをそのまま当てられる（ファイル名を device1/device2 共通の
汎用名にリネームするか、その時に判断する）。
