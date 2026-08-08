# heap free/maxblockのテレメトリを実装する

[接続使い回し(v1.7.0)](2026-08-08-uplink-v1.7.0-conn-reuse.md)の記録時に予備案としてメモした
「heap free/maxblockをバッチ送信ヘッダで定期報告する」（`docs/design.md`未定事項4）を実装した。

## 何をしたか

- firmware: `main.cpp`の`extraRequestHeaderNames/Values`（`fw_version`・`uptime`で
  2枠使用中）に`X-Namz-Heap-Free`（`ESP.getFreeHeap()`）・`X-Namz-Heap-Maxblock`
  （`ESP.getMaxAllocHeap()`）を追加し4枠使い切った。`Uploader::kMaxExtraRequestHeaders`は
  4なので**batch-uplink側の変更は不要**（実装前にユーザーから「4つまで送れなかったっけ」と
  指摘され確認、想定通りだった）
- 保存先をどうするか（ユーザーへ確認）: 最新値の上書きだけでは「何かあった時の調査に
  使いづらい」という指摘を受け、3案（CloudWatchカスタムメトリクス／DynamoDB時系列テーブル
  ＋TTL／現状通り最新値のみ上書き）を提示し**CloudWatchカスタムメトリクス**を選んでもらった。
  既存のDynamoDB中心の構成からは外れるが、time seriesの保持・グラフ化がAWS側で完結し、
  実装コストが一番小さいのが決め手
- ingest: `common/metrics.py`を新設し`boto3.client("cloudwatch").put_metric_data()`で
  `Namespace=Namazu`、`DeviceId`ディメンション付きで`HeapFreeBytes`・
  `HeapMaxAllocBytes`を送る。`device_meta.py`と同じ「主経路ではないので失敗しても
  バッチ保存自体は成功扱い」の方針を踏襲
- terraform: `cloudwatch:PutMetricData`をLambda実行ロールへ追加（このAPIはリソースレベル
  権限に対応しないため`resources = ["*"]`）
- `namazu-devices`テーブル・api Lambdaへの変更は無し（現在値表示は今回のスコープ外、
  CloudWatch側でグラフを見れば足りる）

## 確認したこと

- `pytest lambda/tests`（99件、`test_metrics.py`を新規追加）通過
- firmware esp32dev・adxl355両envのビルド成功
- `terraform validate`成功（実際のapplyはまだ）

## 次に何が可能になったか

CloudWatchの保持期間は解像度に応じて自動で粗くなる（1分解像度15日→5分63日→
1時間455日）。次に実機で障害が起きた時、シリアルログ無しでもCloudWatchの
グラフでheap free/maxblockの推移を事後に追えるようになった。[接続使い回しの
効果検証](2026-08-08-uplink-v1.7.0-conn-reuse.md)（バックフィル中にハンドシェイクが
実際に省略されているか）にもこのメトリクスをそのまま使える見込み。

未apply・未OTA配信。適用するにはterraform applyに加え、firmware側も新しいバージョンを
ビルドしてpull型OTAで配信する必要がある。
