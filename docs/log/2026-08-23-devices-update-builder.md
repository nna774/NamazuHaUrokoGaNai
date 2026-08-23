# ingestのnamazu-devices書き込みを断片＋ビルダー方式に作り直した（デプロイはまだ）

## 背景

[#134](https://github.com/nna774/NamazuHaUrokoGaNai/pull/134)（マージ・デプロイ済み、
[log/2026-08-23-ingest-devices-table-update-item-merge.md](2026-08-23-ingest-devices-table-update-item-merge.md)）は
`watchdog_mute.clear_mute()`と`device_meta.record_sensor_type()`を
`device_meta.record_sensor_type_and_clear_mute()`という1関数へアドホックに結合して
1回のupdate_itemにまとめた。書き込み回数は減ったが、設計としては以下の問題があった:

- `sensor_type`(device_metaの関心事)と`watchdog_muted`(watchdog_muteの関心事)という
  無関係な2つを1関数に混ぜたため、`watchdog_muted`という属性名の知識が
  `watchdog_mute.py`（本来の持ち主）と`device_meta.py`（#134で紛れ込んだ側）の
  2箇所に重複した。
- 将来3つ目の関心事（例: boot_epoch）を同じ書き込みに混ぜたくなったら、また
  `..._and_..._and_...`という組み合わせ関数を手で書く必要があり、関心事の数だけ
  組み合わせ爆発する。

これは「call数を減らせるか」とは別軸の、今この時点で既に単一責任違反という
設計上の問題だったので、書き直した。

## 何をしたか

各モジュールが「実行はしない、SET/REMOVE式の断片だけ返す」関数を公開する形に
変更した:

- `watchdog_mute.clear_mute_fragment()` → `("REMOVE watchdog_muted", {})`
- `device_meta.sensor_type_fragment(sensor_type)` → `("SET sensor_type = :s", {":s": sensor_type})`

新設した`lambda/common/dynamo_update.UpdateItemBuilder`が、これらの断片を集めて
1回の`update_item`にまとめる（SET節・REMOVE節をそれぞれ結合するだけの汎用クラス、
device_id等のドメイン知識は持たない）。`lambda/ingest/handler.py`の`_handle_batch`は

```python
builder = dynamo_update.UpdateItemBuilder()
builder.add(*watchdog_mute.clear_mute_fragment())
builder.add(*device_meta.sensor_type_fragment(b.meta.sensor_type))
builder.execute(_devices_table, b.meta.device_id)
```

という形になり、`device_meta.record_sensor_type_and_clear_mute()`は削除した。
`clear_mute()`・`record_sensor_type()`は単体呼び出し用（`tools/mute_device.py`、
将来の個別呼び出し元）としてそのまま残し、内部で同じ断片を使うようリファクタした
（属性名の知識を断片関数1箇所に集約）。

## 書き込み回数への影響

**変化なし。** #134と同じく「GetItem(get_device) 1 + record_batch内部 2 +
統合UpdateItem 1」＝4回/バッチのまま（内訳は
[memo.mdの検討](../../memo.md)参照）。この変更は設計の整理であり、コスト削減効果は
無い。4回を2回まで減らすには、`batch_uplink.devices.record_batch()`側の断片化と
`get_device()`の先出しという、別の・より大きい（Electabuzzとの協調が要る）変更が
必要で、これは別セッションで検討する。

## 何が可能になったこと

将来devices台帳への書き込みに関心事が増えても（例: boot_epochをここに混ぜたい等）、
その関心事のモジュールが断片関数を1つ追加し、handler側で`builder.add()`するだけで
済むようになった。組み合わせ専用関数を都度書く必要が無い。
