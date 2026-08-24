# namazu-devicesへの書き込みをGetItem 1+UpdateItem 1(2回)まで削減した（デプロイはまだ）

## 背景

[#135](https://github.com/nna774/NamazuHaUrokoGaNai/pull/135)（draft）でingestの
ローカル書き込みを断片＋`dynamo_update.UpdateItemBuilder`方式に作り直したが、
`namazu-devices`への書き込み回数自体は4回/バッチ（GetItem 1 + `batch_uplink.devices.
record_batch()`内部2回 + ローカル統合1回）のままだった。このログはその先——
`record_batch()`側も断片化してBuilderに合流させ、GetItem 1 + UpdateItem 1の
**2回まで削減した**実装。

memo.mdでの検討の通り、「協調」といっても実態はbatch-uplinkへの**追加のみ**の
変更で完結した（既存の`record_batch()`は無傷、Electabuzzの呼び出しには一切影響しない）。

## batch-uplink側

[nna774/batch-uplink#26](https://github.com/nna774/batch-uplink/pull/26)（マージ済み）で
`devices.record_batch_fragments(item, batch_start_us, ingest_at_us, last_batch_key, fw_version)`
を追加した。`record_batch()`と同じ内容を実行せず断片のリストとして返す:

- `last_ingest_at_us`・`last_batch_key`・(あれば)`fw_version`を1つのSET節にまとめる
- `batches_total`のADD節
- `last_batch_start_us`の単調増加は、`record_batch()`のようにConditionExpressionで
  守るのではなく、**呼び出し側が既に取得済みの`item`と比較して**SET節に含めるか
  判断する（追加のDynamoDB呼び出しを増やさないため。同時書き込みへのアトミック性は
  提供しない——デバイス1台からのリクエストが事実上直列な用途に限る前提）

`track_prev_key`は持たない（Electabuzz detect固有機能。そちらは従来通り`record_batch()`を使う）。

**[v3.2.0](https://github.com/nna774/batch-uplink/releases/tag/v3.2.0)としてタグ付け・
push済み。**

## Namazu側

`lambda/common/dynamo_update.UpdateItemBuilder`にADD節対応を追加した
（`record_batch_fragments()`の`batches_total`用）。

`lambda/ingest/handler.py`の`_handle_batch`を以下のように再構成した:

1. `devices.get_device()`を**先頭で1回だけ**呼ぶ（従来は書き込み後・再起動/OTA判定の
   直前の2箇所で呼んでいた`record_batch()`実行後 + 別のGetItemを、この1回に統合）
2. `record_batch_fragments(item, ...)` + `watchdog_mute.clear_mute_fragment()` +
   `device_meta.sensor_type_fragment()`を`UpdateItemBuilder`に集約し、1回`execute()`
3. 後段の再起動/OTA判定・起動検知(`boot_epoch`)は、この最初に取得した`item`をそのまま
   使い回す（バッチ書き込みは`pending_restart_requested_at_us`等に触れないので、
   書き込み前後でこれらのフィールドは変わらない——タイミングをずらしても安全）

`firmware/platformio.ini`（2箇所）・`terraform/build_lambda.sh`の`UPLINK_VERSION`を
`v3.2.0`に更新（CLAUDE.mdの不変条件通り2箇所を揃えた）。

## 書き込み回数への影響

**4回/バッチ → 2回/バッチ**（GetItem 1 + UpdateItem 1）。

- 従来: `get_device()`(GetItem 1) + `record_batch()`内部(UpdateItem 2) + ローカル統合(UpdateItem 1)
- 今回: `get_device()`(GetItem 1) + 全断片統合(UpdateItem 1)

WCU換算では#134後の3回→1回で、さらに67%の削減が見込める
（[log/2026-08-23-devices-table-wcu-verification.md](2026-08-23-devices-table-wcu-verification.md)の
測定方法と同じやり方でデプロイ後に検証できる）。

## テスト

- `lambda/tests/test_dynamo_update.py`にADD節のテストを追加
- `lambda/tests/test_devices_update_integration.py`を新設。`batch_uplink.devices.
  record_batch_fragments()`とローカル断片を実際に組み合わせて1回のupdate_itemに
  なることを検証（新規に取得した`v3.2.0`を`.venv`にインストールして実行）
- `terraform/build_lambda.sh`でingest.zip等4つのビルドが新バージョンで通ることを確認
- `pytest lambda/tests` 158件全パス

## 何が可能になったこと

`namazu-devices`への書き込みが2回/バッチまで下がった。デプロイ・CloudWatchでの
効果測定は未実施（PR段階）。
