# 使っていないLAN内push型OTA(ArduinoOTA)を撤去した

## 概要

- `newBatch()`失敗対策のバッファプール化がDRAM予算の壁で見送りになった件の
  無駄遣い調査（[Shindoの静的24KBバッファ撤去](2026-08-10-shindo-currentintensity-heap-tmp-buffer-removal.md)
  と同じ流れ）で、ArduinoOTA（LAN内push型OTA）が候補に挙がった
- 2026-08-06に実装したが、母艦とデバイスがVLANで分離されており`espota`転送が
  一度も届かなかった（`docs/log/2026-08-06-ota-network-isolation.md`）。ユーザーに
  確認したところ「LAN型OTA、届かないから使っていない。消すとどれぐらい開くかに
  よって消してもいい」との回答
- 削った場合の静的RAM削減量を実測してから、**全部消す**（`main.cpp`のコードだけでなく
  `platformio.ini`の`-ota` env・`DeviceIdentity`の`otaPassword`(NVS)・
  `tools/provision_device.py`の`ota-password`コマンド・関連ドキュメントまで）
  方針をユーザーに確認して撤去した
- 静的RAM使用量が**106092B→102132B（約3.9KB減）**、Flashも約39KB減った
- pull型OTA（HTTPS、実機で自己更新まで成功済み・現在の唯一の更新経路）とは
  `pauseSamplingForOta()`/`resumeSamplingAfterOtaFailure()`（安全停止シーケンス）を
  共有していたため、この2関数はpush専用のコールバック(`otaOnStart`/`otaOnProgress`/
  `otaOnError`)だけ削り、共有部分はそのまま残した

## 削った範囲

- `firmware/src/main.cpp`: `#include <ArduinoOTA.h>`、push専用コールバック3つ、
  `setup()`の`ArduinoOTA.setHostname/setPassword/onStart/onProgress/onError/begin()`、
  `loop()`相当の`ArduinoOTA.handle()`呼び出し、未使用になった`gOtaHostname`バッファ
- `firmware/lib/DeviceIdentity/{.h,.cpp}`: `otaPassword`フィールドとNVSの
  get/put（`ota_password`キー）
- `firmware/src/provision_main.cpp`・`secrets_provision.h.example`:
  `kProvOtaPassword`関連
- `firmware/platformio.ini`: `[env:esp32dev-ota]`/`[env:adxl355-ota]`
  （espotaアップロード方式のenv）
- `tools/provision_device.py`: `REQUIRED_FIELDS`から`ota_password`を除外、
  `new_ota_password()`・`cmd_ota_password`・`ota-password`サブコマンドを削除
- `tools/devices.example.json`・`tools/tests/test_provision_device.py`:
  `ota_password`関連フィールド・テストを削除
- `tools/README.md`・`firmware/README.md`: 使い方の記述を更新
  （firmware READMEはpull型の使い方に差し替え）
- `docs/ota.md`: 全面書き直し。現在の方式（HTTPSプル型）を主軸に再構成し、
  push型は経緯と撤去理由を残す短いセクションに圧縮。§7だったpull型の内容が
  新しい§2になったため、`docs/ota.md §7`を参照していた十数箇所のコメント
  （firmware/lambda/tools）も`§2`に合わせて機械的に更新した
- `docs/STATUS.md`: OTA更新の残タスク項目を「push転送の実機確認待ち」から
  「pull型で実装済み、push型は撤去済み」に更新（`[ ]`→`[x]`）

## 検証

- `pio run -e esp32dev -e adxl355 -e sensortest -e adxl355-sensortest` 全成功
- `firmware/test/run.sh`（wireバイト等価テスト）確認
- `pytest lambda/tests tools/tests`（169件）確認——lambda側はコメントの
  section番号更新のみでロジック変更は無いが、念のため全体を回した
- 静的RAM: esp32dev envで106092B→102132B（3960B減）、Flash: 1081433B→1041889B
  （約39KB減）

## 次に何が可能になったか

`newBatch()`失敗対策のバッファプール化に使えるDRAM予算が、
[Shindoの静的バッファ撤去](2026-08-10-shindo-currentintensity-heap-tmp-buffer-removal.md)
と合わせて約28KB分回復した。プールのスロット数見積もり直しは可能になったが、
結合試験で見つかった他の問題（`kMaxRamBatches=0`のUploader未定義動作、
`pump()`の原因不明の停滞）はDRAM予算とは別の話で未解決のまま残っている。
実機（device1/device2）への投入はまだ。

このPRはShindoの修正（別PR）とは独立に成立する——どちらの順でマージしても
コンフリクトしない見込み（触っているファイルが重ならない。`main.cpp`の
編集箇所も別関数）。
