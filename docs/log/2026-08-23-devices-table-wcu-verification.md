# #134デプロイの効果をCloudWatchで実測した

## 背景

[#134](https://github.com/nna774/NamazuHaUrokoGaNai/pull/134)
（[log/2026-08-23-ingest-devices-table-update-item-merge.md](2026-08-23-ingest-devices-table-update-item-merge.md)）は
`namazu-devices`へのローカル書き込み2回(`watchdog_mute.clear_mute`/`device_meta.record_sensor_type`)を
1回に統合した。当時は「terraform applyはまだ」で効果測定は未実施だった。

このログはその後の作業: **#134をmerge・terraform applyし、直後にCloudWatchで
効果を確認した**記録。

## デプロイ

ローカルで`worktree-bridge-cse_01LwozkcGU2Hw1TdnLryy3CC`ブランチに`git merge origin/master`
してからマージした（GitHubの「マージボタン」は`.gitattributes`の`merge=union`ドライバを
見ないため、`docs/progress.md`の並行追記が原因で`mergeable: CONFLICTING`と表示されていたが、
ローカルの`git merge`ではunionドライバが効きクリーンに解決できた）。

`terraform/build_lambda.sh` → `terraform apply`でingest/api/detect/watchdogの4 Lambdaを更新
（追加・削除なし、コード更新のみ）。**デプロイ完了: 2026-08-23T11:29:55Z**
（ingest Lambda自体の更新完了はこの数十秒前）。

## CloudWatchでの確認

`namazu-devices`テーブルの`ConsumedWriteCapacityUnits`を1分粒度でCloudWatchから取得:

```bash
aws cloudwatch get-metric-statistics --region ap-northeast-1 \
  --namespace AWS/DynamoDB --metric-name ConsumedWriteCapacityUnits \
  --dimensions Name=TableName,Value=namazu-devices \
  --start-time 2026-08-23T11:10:00Z --end-time 2026-08-23T11:36:00Z \
  --period 60 --statistics Sum
```

結果:

| 時刻帯 | WCU/分 |
|---|---|
| デプロイ前 (〜11:28) | 27〜32（ばらつきあり、概ね32） |
| デプロイ後 (11:29〜11:35) | **24で安定** |

デプロイ時刻(11:29)を境に段差が即座に出た。Cost Explorerは反映まで実質1日近く
遅延するが、CloudWatchのDynamoDBメトリクスは1分粒度でほぼリアルタイムに見える
（数分の観測で判断できた）。

## 32→24という数字の解釈

比率は0.75。これは**GetItemはWCUを消費しない**ことを踏まえると、
`devices.get_device()`を除いた「WCU換算の呼び出し回数」の変化と正確に一致する:

- #134前: `record_batch()`内部2回 + `clear_mute()`1回 + `record_sensor_type()`1回 = **4回**
- #134後: `record_batch()`内部2回 + 統合後1回 = **3回**
- 比率 3/4 = 0.75 → 32 × 0.75 = 24 ✓

（`get_device()`を含めた「総API呼び出し数」で言えば5回→4回だが、それはRCU側の話で
WCUの実測値とは分母が違う。両者を混同しないこと。）

## 次に可能になったこと

#134の効果は実測で裏付けられた。#134自体の設計（`record_sensor_type_and_clear_mute()`が
無関係な関心事をアドホックに1関数へ結合していた点）の作り直しは
[#135](https://github.com/nna774/NamazuHaUrokoGaNai/pull/135)
（draft、書き込み回数への影響は無し）で対応済み。

さらに`get_device()`の先出し＋`record_batch()`側の断片化まで進めれば
GetItem 1 + UpdateItem 1の2回まで削減できる見込みだが、これは`batch_uplink`側の
API変更（Electabuzzとの協調が要る）を伴う別の大きい変更として未着手のまま。
