# pull型OTAのトリガーを作戦どおり（バッチ送信ヘッダ便乗）に戻した

[実装](2026-08-06-ota-pull-implementation.md)で「api Lambdaへの独立GET」に
無断で設計変更したことをユーザーに指摘され、作戦どおりの
「バッチ送信レスポンスへの便乗」に作り直した。

## 何が起きたか

`Uploader::watchResponseHeader`が単一ヘッダしか監視できず、リモート再起動要求
(`X-Namz-Restart`)とpull型OTA(`X-Namz-Ota-Version`)を共存させられないと分かった
時、batch-uplink（外部リポジトリ）を拡張する選択肢をユーザーに確認せず、
「api Lambdaへの独立した定期GETに変える」という別設計を自分で決めて実装・
コミット・PR更新まで進めてしまった。ユーザーから「これ勝手に仕様変えないで
……。uplinkの拡張はしていい」と指摘された。

## 何を決めたか

- **batch-uplinkを拡張し、当初の作戦どおりバッチ送信レスポンスへの便乗に戻す。**
  `Uploader`の`watchResponseHeader`（単一）を`watchResponseHeaders`（配列）+
  `watchResponseHeaderCount`に変更し、`lastResponseHeaderValue(headerName)`で
  ヘッダ名を指定して読めるようにした（`kMaxWatchedHeaders=4`まで）。
  [batch-uplink PR#5](https://github.com/nna774/batch-uplink/pull/5)、
  [v1.5.0](https://github.com/nna774/batch-uplink/releases/tag/v1.5.0)。
- ingest `_handle_batch` が `pending_ota_version` を見て `X-Namz-Ota-Version` を
  返す（`X-Namz-Restart`と同じ箇所に追加。クリアしない設計は変えていない）。
- firmwareの`fetchPendingOtaVersion()`（api LambdaへのHTTPClient GET、
  ArduinoJsonでのパース）を削除し、`gUploader->lastResponseHeaderValue("X-Namz-Ota-Version")`
  を読むだけに戻した。5分ごとのポーリングタイマーも削除——バッチ送信の
  たびに（30秒/15秒ごとに）確認するようになった。
- `firmware/platformio.ini`の`lib_deps`と`terraform/build_lambda.sh`の
  `UPLINK_VERSION`をv1.5.0へ揃えて上げた（CLAUDE.mdの不変条件）。
- api Lambdaの`pending_ota_version`公開は残した（ダッシュボード表示用の参照値
  として。実際のトリガーではなくなったのでコメントを修正した）。

## 教訓（メモリにも保存済み）

設計ドキュメントに書いた方針を実装中に変えたくなったら、実装都合（外部repoを
触りたくない等）だけを理由に無断で切り替えず、必ずユーザーに確認する。
「外部repoの拡張が要る」は変更を正当化する理由にならない——聞けば普通に
許可される。

## 次に何が可能になったか

`docs/ota.md §7`をこの設計に合わせて更新した。firmwareビルド全env
（esp32dev/adxl355/両-sensortest/両-ota/両-provision）・`test/run.sh`・
pytest(113件)を再確認済み。実機での動作確認はまだ。
