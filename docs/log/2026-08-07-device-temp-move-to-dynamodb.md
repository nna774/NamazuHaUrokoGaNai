# 温度トレンドの取得方式を S3 Range GET から ingest時DynamoDB記録に作り直した

[前のログ](2026-08-07-device-detail-page-temp-trend.md)で作った「読み取り時に raw/ を
ヘッダ+トレイラーだけ Range GET する」設計を、同日中に破棄して作り直した。

## 何を決めたか

- 新設 DynamoDB テーブル`namazu-device-temp`(pk=device_id, sk=batch_start_us, TTL付き)を追加。
- **ingest** が受信バッチを`wire.parse()`した直後、温度トレイラーがあれば1件 PutItem する
  （`lambda/common/device_temp.py`の`record()`）。
- **api** の`/devices/<id>/temp`は`device_temp.query_range()`で DynamoDB を Query するだけになり、
  S3には一切触らない。
- `lambda/common/store.py`の`load_temp_series`、`wire.py`の`parse_header`/`payload_size`は削除
  （前ログの設計でしか使っていなかった）。`wire.temp_c`は`temp_c_for(sensor_type, raw)`に
  分離し、DynamoDBアイテム（BatchMetaを経由しない）からも同じ換算ロジックを使えるようにした。

## なぜ覆したか

ユーザーから「ヘッダ+トレイラーの2回 Range GET、続けてると結構高くなる？集計してどこかに
温度だけ持つほうがよくないか」と指摘され、計算し直したら前ログの「軽量」という言葉が
不正確だったと分かった。

- **S3のGET料金はリクエスト数課金でサイズに依らない**（同リージョン内のS3→Lambda転送は
  無料）。ヘッダ→トレイラーの2分割は**リクエスト数がむしろ2倍**になる方向で、「安くなる」
  という表現は誤りだった。実際に軽くなっていたのは転送バイト数とnumpyパースのCPU
  （＝Lambda実行時間課金）だけで、S3料金の節約にはなっていなかった。
- しかも`/devices/<id>/temp`は**認証なし公開API**。閲覧されるたび（将来ライブビューに
  自動更新ポーリングを足せば尚更）にS3アクセスが発生する設計は、見られる回数に比例して
  際限なく課金が増えうる。件数の頭打ちは`max_points`が担っていたが、これは「1回あたりの
  上限」であって「叩かれる回数」には無力だった。
- **ingestは受信バッチを既に`wire.parse()`している**。温度トレイラーの取り出しに追加の
  S3アクセスは要らない——読み取り時に毎回作り直す代わりに、書き込み時に1回だけ記録して
  おけばよいと気づいた。書き込み頻度はバッチ受信頻度（15〜30秒に1回・デバイス台数分）に
  固定され、**読まれる回数に左右されない**。DynamoDBのオンデマンド書き込みはS3 GETより
  さらに安く、公開APIを叩かれても書き込みコストは増えない。

## 何が覆ったか

- [前ログ](2026-08-07-device-detail-page-temp-trend.md)の「Range GETでヘッダ→トレイラーの
  2回読みにする」設計は全面的に撤回。`store.load_temp_series`・`wire.parse_header`・
  `wire.payload_size`は削除した。
- api の応答形式（`{device_id, hours, points: [{t, raw, c}]}`）とダッシュボード側
  （`dashboard/app.js`の`refreshDeviceTemp`/`drawTempChart`）は変更なし。バックエンドの
  取得方式が変わっただけで、フロントエンドとの契約は保たれている。

## 次に何が可能になったか

- 読み取りコストが「見られる回数」から実質的に解放されたので、将来ライブビューに温度を
  重ね描きする案（前ログに残した未実装アイデア）を自動更新ポーリング込みで作っても、
  S3コストの心配をしなくてよくなった。
- 温度専用テーブルができたので、将来「架台の熱ドリフト補正」のような温度を使った
  後処理（例えば震度算出への補正）を足す時も、このテーブルをQueryするだけで済む。

## 動作確認

- `pytest lambda/tests`: 86件全通過（`device_temp`の記録・照会テストを新規追加、
  S3 Range GET関連の旧テストは削除）。
- `terraform validate`（`-backend=false`、リモートstateには触れていない）で新テーブル・
  IAM権限・Lambda環境変数の構文を確認済み。
- ダッシュボードの動作確認は前ログの内容から変わらない（apiの応答形式が同じなので
  フロントエンドは無改修）。
- **実機・本番デプロイはまだ**（terraform applyもdashboardデプロイも未実施）。
