# ingestの`namazu-devices`書き込みを1回のupdate_itemに統合した（デプロイはまだ）

## 背景

[2026-08-23のコスト調査](2026-08-23-s3-dynamodb-cost-cross-account-investigation.md)で、
`namazu-devices`テーブルへの書き込みが毎バッチ・同一device_idに対しGetItem1回+
UpdateItem3回に分かれており、そのうち`watchdog_mute.clear_mute()`と
`device_meta.record_sensor_type()`はローカルコードなので統合可能と判明していた。
このログはその実装。

## 何をしたか

`lambda/common/device_meta.py`に`record_sensor_type_and_clear_mute()`を追加し、
`SET sensor_type = :s REMOVE watchdog_muted`という単一のUpdateExpressionで
両方を1回のupdate_itemにまとめた。`lambda/ingest/handler.py`の`_handle_batch`は
これまで別々のtry/exceptで呼んでいた`watchdog_mute.clear_mute()`と
`device_meta.record_sensor_type()`をこの1呼び出しに置き換えた
（`namazu-devices`へのローカル書き込みがUpdateItem2回→1回に減る）。

既存の`watchdog_mute.clear_mute()`・`device_meta.record_sensor_type()`は関数として残した。
前者は`tools/mute_device.py`のCLIから単体で呼ばれている（sensor_typeを知らないため
統合版は使えない）。後者は単体テストの対象として、また将来sensor_typeだけ
書き込みたい呼び出し元が出た場合のために残した。

新関数の配置先（`device_meta.py` vs `watchdog_mute.py` vs handler.py直書き）は
設計判断が要ったため実装前にユーザーに確認し、「`device_meta.py`に追加」を選んだ
（既にNamazu固有属性のupdate_itemをまとめている場所であるため）。

## 何が可能になったこと

`namazu-devices`への書き込みがバッチあたり1回減った分、DynamoDBのWCUが
削減される見込み。効果測定にはCloudWatchの`ConsumedWriteCapacityUnits`推移を
デプロイ後しばらく追う必要がある。**`terraform/build_lambda.sh`＋`terraform apply`は
まだ実行していない。**

GetItem（`devices.get_device`）の統合は、コスト調査ログの通りRead単価が軽いため
見送ったまま（未着手）。
