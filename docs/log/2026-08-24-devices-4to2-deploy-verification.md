# #135・#137をマージ・デプロイし、4→2への削減をCloudWatchで実測した

## 背景

[#135](https://github.com/nna774/NamazuHaUrokoGaNai/pull/135)（アキュムレータ方式への
作り直し）・[#137](https://github.com/nna774/NamazuHaUrokoGaNai/pull/137)（batch-uplink
[v3.2.0](https://github.com/nna774/batch-uplink/releases/tag/v3.2.0)を使った4→2回/バッチへの
削減、[log/2026-08-23-devices-batch-uplink-consolidation.md](2026-08-23-devices-batch-uplink-consolidation.md)）
をマージ・terraform applyし、[前回](2026-08-23-devices-table-wcu-verification.md)と同じ手法で
CloudWatchから効果を確認した記録。

## マージ

- #135: GitHub上は`mergeable: CONFLICTING`（`.gitattributes`のunion driverをGitHubのマージ
  ボタンが見ないため、progress.mdの並行追記が原因）。`git checkout`→`git merge origin/master`→
  pushでローカルにクリーンに解決してからマージした（#134と同じ手順）。またdraft PRだったため
  `gh pr merge`が"still a draft"で一度失敗し、`gh pr ready`してから再実行した。
- #135マージ後、そのbaseブランチ`worktree-devices-update-builder`が削除され、#137
  （このブランチにstackしていた）のbaseはGitHubが自動でmasterへretargetした。#137も
  同様にローカルで`git merge origin/master`してからマージした。

## デプロイ

`terraform/build_lambda.sh` → `terraform apply`で4 Lambdaを更新（追加・削除なし）。
**デプロイ完了: 2026-08-24T00:49:29Z頃**。

## CloudWatchでの確認

`namazu-devices`の`ConsumedWriteCapacityUnits`（1分粒度）:

| 時刻帯 | WCU/分 |
|---|---|
| デプロイ前 (〜00:47) | **24で安定**（#134後の定常状態） |
| ロールアウト中 (00:48) | 16（Lambdaの新旧コードが混在する遷移分） |
| デプロイ後 (00:49〜00:52) | **8で安定** |

24→8は比率1/3。GetItemを除いたWCU換算の呼び出し回数で言うと:

- #134後: `record_batch()`内部2回 + ローカル統合1回 = **3回**
- #137後: 全断片統合1回 = **1回**
- 比率 1/3 = 24 × (1/3) = 8 ✓

[前回のPR#134デプロイ](2026-08-23-devices-table-wcu-verification.md)の32→24（比率0.75）に続き、
今回も予測通りの段差がデプロイの数分後には出た。デプロイのロールアウトが1分程度かかる
（新旧コードが混在する過渡期がCloudWatch上にも見える）点は今回新たに観測できた知見。

## DynamoDBの中身とLambdaログの健全性確認

WCUの数字だけでなく、実際に書かれているデータとエラーの有無も見た。

`namazu-devices`を`scan`して4件（device 1・2・3・稼働機、および試験用device
`4294967295`）を確認:

- 稼働中のdevice 1・2・3は`sensor_type`・`fw_version`・`batches_total`・
  `last_batch_start_us`・`last_ingest_at_us`が正常値。`watchdog_muted`属性は
  **存在しない**——mute中でない機体にはREMOVE節が効いて属性ごと消えている
  （`if_not_exists`を使わず無条件REMOVEにしている設計通り）
- `last_batch_start_us`と`last_ingest_at_us`の差は各機体16〜31秒で、30秒バッチ
  間隔と整合。単調性判断をConditionExpressionからPython側の比較に変えた影響で
  巻き戻り・停止は起きていない
- `batches_total`は3台とも大きい値（35415/120808/117618）でデプロイを跨いで
  途切れずカウントアップしている（ADD節の値が壊れていない）
- 試験用device`4294967295`（mute中、直近バッチなし）は`watchdog_muted: true`の
  まま——バッチが来ていないのでREMOVE節が実行されておらず、想定通り
- 型（N/S/BOOL/L）もすべて期待通りで、Decimal周りの取り扱いで壊れている様子はない

`/aws/lambda/namazu-ingest`のログをデプロイ後の時間帯で確認したところ、
`print(f"... failed: {e!r}")`系のエラーメッセージは1件も出ておらず、
START/END/REPORTのみで正常終了（Duration 148〜623ms、異常な遅延なし）。

## 何が可能になったこと

`namazu-devices`への書き込みは当初の5回/バッチ（#134前）から2回/バッチまで削減され、
実測でも裏付けられた。この系列の最適化はここで一区切り——次にさらに削減する余地が
あるとすれば`get_device()`のGetItem自体だが、コスト調査ログの通りRead単価が軽いため
優先度は低いままにしておく。
