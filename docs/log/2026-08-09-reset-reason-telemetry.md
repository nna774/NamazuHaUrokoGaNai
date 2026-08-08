# 直前の再起動理由(esp_reset_reason)を送信・記録・表示する

[batch-uplinkのヘッダ配列nullptr終端化](2026-08-09-uplink-v2.0.0-sentinel-header-arrays.md)
で枠の上限を撤去した本来の目的。device1/device2の予期しない再起動が
[WDT panic説](2026-08-08-wdt-panic-hypothesis.md)（TLSハンドシェイクがWDTの10秒より
先に詰まりpanic再起動する）とヒープ枯渇説のどちらなのか、実機データで切り分ける
ための可観測性を足した。

## 何をしたか

- firmware: 起動時(`setup()`先頭)に`esp_reset_reason()`を1回だけ読み、
  `resetReasonToString()`で短い文字列(`POWERON`/`PANIC`/`TASK_WDT`等、ESP-IDF
  4.4.7の`esp_reset_reason_t`が持つ全値をカバー)に変換して`X-Namz-Reset-Reason`
  ヘッダで毎バッチ送る。
  - 値は起動後変わらないが、`sResetReasonBuf`という固定アドレスのバッファに
    コピーする方式にした（uptime/heapと同じ）。単純な`const char*`変数を
    setup()で差し替える案は、`kExtraRequestHeaderValues[]`が静的初期化時に
    ポインタの**値**をコピーして持つため、後から変数を差し替えても配列側には
    反映されないバグになると気づき、実装中に直した。
  - `resetReasonToString()`等は`#ifndef NAMZ_SENSOR_TEST`ブロック内（Uploader関連の
    定義と同じ場所）にあるため、setup()側の呼び出しも同じ`#ifndef`で囲む必要が
    あった（最初漏らしてsensortest環境のビルドを壊しかけた、`pio run`で発覚）。
- ingest: `device_meta.record_boot_epoch()`に`reset_reason`引数を追加。
  再起動検知時（`should_update_boot_epoch()`がTrue）の同じUpdateItemに相乗りさせる
  （追加のDynamoDB書き込みは発生しない）。ヘッダが無ければ（旧ファーム）
  フィールド自体を書かず、前回値を消さない。
- api: `/devices`・`/devices/<id>`の`_device_view()`に`reset_reason`を追加
  （`boot_epoch_us`/`uptime_s`と同じ並び。CloudWatch呼び出し不要な単純な
  DynamoDBフィールドなので一覧・詳細どちらにも出る）。
- dashboard: デバイス詳細ページの「稼働時間」行の下に「前回の再起動理由」行を
  追加（一覧テーブルには足さない、既存の稼働時間表示と同じ扱い）。

## 確認したこと

- `pio run -e esp32dev -e adxl355 -e sensortest -e adxl355-sensortest` 全てSUCCESS
- `firmware/test/run.sh` PASSED
- `pytest lambda/tests`（106件、`device_meta`のreset_reason有無・`api`の
  reset_reason露出のテストを追加）

**terraform apply・実機OTA配信はまだ。** ファーム側のバージョンpin更新([batch-uplink
v2.0.0への追従](2026-08-09-uplink-v2.0.0-sentinel-header-arrays.md))と合わせて、
まとめてOTA配信する予定。

## 次に何が可能になったか

次回device1/device2が予期せず再起動した時、デバイス詳細ページの「前回の再起動理由」
を見るだけで`TASK_WDT`（WDT panic説を裏付ける）か`BROWNOUT`/`POWERON`（別原因）かが
その場で分かる状態になった。CloudWatchのheapテレメトリと突き合わせれば、WDT panic説と
ヒープ枯渇説の切り分けがほぼ完成する。
