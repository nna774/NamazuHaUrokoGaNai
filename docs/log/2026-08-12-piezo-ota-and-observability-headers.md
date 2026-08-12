# device3(ピエゾ)にpull型OTAと可観測性ヘッダを移植した

## 発端

device3(ピエゾ実験機、`piezo_main.cpp`)の`fw_version`がAPI(`/devices/3`)で
空文字のままだと気づいた。phase1実装ログ(2026-08-12)で「OTA・複雑な信頼性
機構は今回見送り」としていたのがそのまま現状として残っていただけで、故障
ではなかった。別セッションの調査で、本線`main.cpp`が送っている以下のヘッダを
device3が一切送っていないと判明した——`Uploader`のコンストラクタで
`extraRequestHeaderNames/Values`と`watchResponseHeaders`を丸ごと`nullptr`に
していたため:

- `X-Namz-Fw-Version`（版数）
- `X-Namz-Uptime-Us`（稼働時間）
- `X-Namz-Heap-Free` / `X-Namz-Heap-Maxblock`（ヒープ）
- `X-Namz-Reset-Reason`（再起動理由）
- `X-Namz-Spill-Count` / `X-Namz-Ram-Queued`（未送信バックログ）
- `X-Namz-Restart`監視（リモート再起動）

これらの仕組み自体は`Uploader`の汎用API（`batch-uplink`側は変更不要）なので、
本線から値の出し方だけ移植すればよいと判断し、OTA本体も含めて段階的に
実装した。

## 作戦（実装前にまとめた方針）

1. 可観測性ヘッダ全部+リモート再起動監視を先に足す（独立・低リスク）
2. `get_fw_version.py`の`_ota_env()`を直す（`adxl355`/`esp32dev`の2択決め打ちで
   `piezo`は`esp32dev`にフォールバックしていた——直さずOTAを有効化すると
   配布URLを取り違える事故になる）
3. 安全停止シーケンス(`pauseSamplingForOta`/`resumeSamplingAfterOtaFailure`)を
   移植
4. `performPullOta`/`checkAndPerformPullOta`を移植、`X-Namz-Ota-Version`監視を追加
5. `publish_ota.sh`にpiezo env対応を追加
6. パーティション構成を実ビルドで確認

## 実装

### 1〜4: firmware側（`piezo_main.cpp`・`piezo_config.h`）

本線`main.cpp`とほぼ同じロジックをそのまま移植した。シングルコア
(ESP32-C3)でも設計は変わらない——フラッシュ書き込み中は命令フェッチが
止まるため測定タイマー(`gSampleTimer`)を止める必要があるのは本線と同じ
理由。TLS二重接続回避の`gUploader->closeConnection()`も踏襲した
（ESP32-C3はRAM総量が本線より少ない分、TlsMemPoolの固定サイズを超える
リスクはむしろ本線より高いと判断）。

本線と違い、ボタン長押しによる緊急手動再起動・TFT表示連動
(`gOtaInProgress`)は無い（piezoにその機構自体が無い）ので移植していない。

Amazon Root CA 1の埋め込み(`board_build.embed_txtfiles`)はphase1実装時点で
既にingest接続用に済んでいたため、OTA取得先(CloudFront)の検証にもそのまま
使い回せた。

### 2: `get_fw_version.py`

`_ota_env()`に`piezo`判定を追加。`PIOENV`が`piezo`/`piezo-provision`のどちらも
`piezo`を返す。

### 5: `publish_ota.sh`

`case`文に`piezo`を追加。OTA_ENV文字列とPIOENV/NAMZ_OTA_ENVがどれも
"piezo"で一致するため、esp32dev/adxl355と同じ経路がそのまま動く。

### 6: パーティション確認

`pio run -e piezo`後の`.pio/build/piezo/partitions.bin`を
`gen_esp32part.py`で実際にデコードして確認した:

```
nvs,data,nvs,0x9000,20K,
otadata,data,ota,0xe000,8K,
app0,app,ota_0,0x10000,1280K,
app1,app,ota_1,0x150000,1280K,
spiffs,data,spiffs,0x290000,1408K,
coredump,data,coredump,0x3f0000,64K,
```

本線(esp32dev/adxl355)と全く同じ`default.csv`相当のOTA対応レイアウト
（app0/app1各1.25MB）だった。board側に`board_build.partitions`の明示指定は
無いが、ESP32-C3スーパーミニ(flash 4MB)でもフレームワーク既定でOTA可能な
パーティション構成になっている。firmware.binの実サイズは959,836/1,310,720
バイト(73.2%)——本線esp32dev(78%)と近い余裕感で、パーティション変更は不要
と判断した。

## 確認したこと・していないこと

- `pio run -e piezo` / `-e esp32dev` / `-e adxl355` / `-e sensortest` /
  `-e fake-sensor` 全て成功、回帰なし
- `firmware/test/run.sh`（ワイヤ形式のゴールデンテスト）通過
- `piezo-provision`は`secrets_provision.h`（gitignore対象、生成物）が
  無い開発環境では元々ビルドできない（`provision`envも同様に失敗することを
  確認済み、今回の変更起因ではない）
- **実機投入・実際のOTA転送確認はまだ**。device3は現在稼働中の機体なので、
  次にやるなら`tools/publish_ota.sh piezo`でビルド・公開し、
  `tools/request_ota.py request 3 <version>`で許可を出し、`/devices/3`の
  `fw_version`が一致するかで確認する（`docs/ota.md §0`クイックリファレンス
  と同じ手順）

## 次にできること

- device3への実OTA投入・実機確認
- 落ち着いたら`docs/STATUS.md`「デバイス一覧」に3号機を追記
  （`docs/log/2026-08-12-piezo-phase1-impl.md`のTODOに既出、今回は未着手）
