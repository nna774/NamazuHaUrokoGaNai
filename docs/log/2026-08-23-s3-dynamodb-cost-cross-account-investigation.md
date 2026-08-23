# S3・DynamoDBコスト増の内訳をアカウント横断で調査した（実装はまだ）

## 何を調べたか

`~/Downloads/costs.csv`（AWS Cost ExplorerのS3操作別日次コスト）を発端に、
S3コスト増の原因を調査した。続けて`~/Downloads/costs-d.csv`（同様のDynamoDB版、
PayPerRequestThroughputが支配的）についても同じ切り口で調べた。**このログは調査結果
のみで、実装は別セッションに切り出す。**

## S3側: 3つの別々の要因が積み重なっていた

日次コストをGetObject/PutObject/ListBucket別に分解し、各段差の日付をこのリポジトリと
[Electabuzz](https://github.com/nna774/Electabuzz)（同じAWSアカウントに同居する、
商用電力系統周波数を測る別プロジェクト）の`docs/progress.md`の日付と突き合わせた。

| 期間 | 現象 | 原因 |
|---|---|---|
| 7/12〜 | GetObjectが0.01→0.11ドル/日に | Namazuのterraform導入・本番稼働開始（想定通り） |
| 8/2〜8/7 | GetObjectが最大0.34ドル/日に一時急増 | Namazu自身の`/recent`バグ（`load_window`が窓外バッチも一旦GETしてから捨てていた）。8/7デプロイの修正日と急落日がぴったり一致、**既に修正済み**（[log/2026-08-07-recent-endpoint-unbounded-get-fix.md](2026-08-07-recent-endpoint-unbounded-get-fix.md)） |
| 8/8〜 | GetObjectは収まったのにPutObject/ListBucketが高止まり | **Electabuzzのingestが8/7 terraform apply・8/8から実機で30秒間隔の常時PUTを開始**したため。Namazuとは無関係の別プロジェクトの通常運用コスト |
| 8/17〜 | ListBucketがさらに底上げ | Electabuzzのdetect Lambda apply日と一致。`_prev_boundary_sample_batch`が毎バッチ`list_objects_v2`で直前キーを探しに行く実装（`lambda/detect/handler.py`）が原因と特定 |
| 8/21 | ListBucketが単日0.088ドルへスパイク | 同日Namazu側で「hachijo-oki M5.5の事後検知」作業をしており、`detectlab.py`等のS3走査が乗った可能性が高い |

Electabuzz側の調査結果・修正案は`electabuzz-data-486414336274`バケットを直接確認の上
`../Electabuzz/takai.md`にまとめ、あちらのセッションへ引き継いだ（このリポジトリの
範囲外なので実装はしない）。

## DynamoDB側: こちらは逆にNamazu自身が支配的

`costs-d.csv`はS3と違って階段状ではなく滑らかに増加していたため、CloudWatchの
`ConsumedWriteCapacityUnits`/`ConsumedReadCapacityUnits`を全テーブル分実測し
（7/8〜8/23合計、書き込み単価は読み取りの約5倍として加重）、寄与を按分した。

| グループ | 加重スコア | 割合 |
|---|---|---|
| Namazu（`namazu-devices`/`namazu-events`/`namazu-device-temp`） | 5,482,922 | **83.0%** |
| Electabuzz（`electabuzz-devices`/`-events`/`-te-anchors`） | 441,477 | 6.7% |
| 無関係の他プロジェクト（`momochi`/`home-atmosphere-mgmt`/`s-nna774-net`等、同一AWSアカウント同居） | 682,874 | 10.3% |

S3と違ってDynamoDBはElectabuzzの寄与が小さい。**主犯はNamazu自身**:

- **`namazu-events`の読み取りが1,251,996 RRUで突出**——`/event`エンドポイントの
  DynamoDB参照。今日apply済みのCloudFrontキャッシュ（[log/2026-08-23-api-cloudfront-recent-event-cache.md](2026-08-23-api-cloudfront-recent-event-cache.md)）で今後自然に下がる見込み。**追加対応不要**
- **`namazu-devices`の書き込みが689,364 WRUで最大**——`lambda/ingest/handler.py`の
  `_handle_batch`が、**毎バッチ・同一device_idの同一項目に対して別々のAPI呼び出しを
  4回**行っている: `devices.get_device()`(GetItem、再起動/OTA確認用)、
  `batch_uplink.devices.record_batch()`(UpdateItem、共有ライブラリ)、
  `watchdog_mute.clear_mute()`(UpdateItem、`REMOVE watchdog_muted`をmute中で
  なくても毎回無条件で呼んでいる)、`device_meta.record_sensor_type()`
  (UpdateItem、`SET sensor_type`)。DynamoDBは呼び出し単位で課金されるため、
  論理的に1回で済む書き込みが分割された分だけ余計にWCUを消費している

## 未実装の改善案

`clear_mute`と`record_sensor_type`はどちらもNamazu固有のローカルコード
（`lambda/common/`、共有ライブラリ`batch_uplink`の外）なので、1回の`update_item`に
統合できる:

```python
_table().update_item(
    Key={"device_id": device_id},
    UpdateExpression="SET sensor_type = :s REMOVE watchdog_muted",
    ExpressionAttributeValues={":s": sensor_type},
)
```

`REMOVE`は対象属性が無くても失敗しない仕様なので、mute中でなくても安全に混ぜられる。
これでこの部分のUpdateItem呼び出しが3回→2回になり、該当分のWCUを約1/3削減できる見込み。
`batch_uplink.devices.record_batch()`は共有ライブラリ側の関数なのでここには含めない
（Electabuzzとの共有部分に影響する変更になるため）。

GetItem（`devices.get_device`）の統合も理論上は可能だが、Read単価はWriteの約1/5と
軽いため優先度は低いと判断し、今回は見送った。

## 次に可能になったこと

`clear_mute`+`record_sensor_type`統合の実装は、別セッションで着手できる状態になった。
