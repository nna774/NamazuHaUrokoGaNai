# デバイス生存台帳に版数を記録し、ダッシュボードに再起動要求・OTA状況を出す

## 何を決めたか

1. batch-uplinkの`Uploader`に「バッチPOSTのたびに固定リクエストヘッダを付ける」
   オプトインAPI(`extraRequestHeaderNames/Values/Count`、最大4本)を追加した。
   既存の`watchResponseHeaders`(レスポンスヘッダ監視)と対称の設計で、この層は
   ヘッダを送るだけで意味づけを持たない。`batch_uplink.devices.record_batch`には
   `fw_version`引数を追加した（空なら書かない、既存呼び出し側と互換）。
   [PR#6](https://github.com/nna774/batch-uplink/pull/6)・
   [v1.6.0](https://github.com/nna774/batch-uplink/releases/tag/v1.6.0)。
2. firmwareは毎バッチ`X-Namz-Fw-Version`ヘッダに`kFwVersion`(ビルド時のgit短縮hash)
   を乗せて送るようにした。ingestがこれを読み`devices.record_batch`へ渡し、
   `namazu-devices`テーブルの`fw_version`属性として記録する。
3. api Lambdaの`/devices`に`fw_version`・`pending_restart_requested_at_us`を追加した
   （`pending_ota_version`は既に出ていた）。ダッシュボードのデバイス一覧に
   「版数」「再起動要求」「OTA」列を追加し、OTAは目標版数と現在の`fw_version`を
   比較して「適用済み」/「取得・適用待ち」を色分け表示する。
4. `firmware/platformio.ini`のlib_depsと`terraform/build_lambda.sh`の
   `UPLINK_VERSION`をv1.6.0へ揃えた。

## なぜそう決めたか

memo.mdの要望「ダッシュボードで再起動要求・OTA要求がかかっているか見たい」
「insert時にhashをヘッダへ乗せて外から動作バージョンが分かるようにしたい」から。
`docs/ota.md`§7末尾の未決事項1「watchdogの停滞検知はデバイスの現在バージョンを
知らないので原因の切り分けができない」も、この変更で解消できる
（サーバがバージョンを知っていれば「まだ古いまま」か「新しいが別の理由で
`pending_ota_version`が消えていない」かを外から区別できる）。

伝達経路はリモート再起動・pull型OTAと同じ「バッチ送信への便乗」を踏襲した。
新しいエンドポイントを作らず、既存のヘッダ機構を対称に拡張しただけなので
firmware側の変更が小さい。

複数ヘッダ対応にしたのはユーザーの指摘。単一ヘッダの設計案を最初に出したが、
「複数取れる方がよくないか」と直された。`watchResponseHeaders`が既に
配列設計（最大4本）だったので、そちらと対称にする方が一貫性がある
——将来ヘッダをもう1本足したくなった時にUploaderへ触らずに済む。

## 何が覆ったか

なし。設計は最初の複数ヘッダ対応への修正のみで、方向性自体は最初から
「既存の便乗パターンを踏襲する」で一貫していた。

## 次に何が可能になったか

- ダッシュボードで再起動要求・OTA適用状況を一目で確認できる。
- watchdogのOTA停滞通知に「現在バージョン」を添えられる（未着手。
  `ota_watch.evaluate_ota_stuck`は`pending_ota_version`しか見ていない）。
- **実機で確認した**（2026-08-06、device 2）。`tools/publish_ota.sh`相当の手順で
  `ota/adxl355/c64f379.bin`をCloudFrontへ公開し、`tools/request_ota.py request 2
  c64f379`で許可。次のバッチ送信でdevice 2が気づき、安全停止→取得→書き込み→
  再起動→復帰まで通しで成功した。`/devices/2`の`fw_version`が`c64f379`（=
  `pending_ota_version`と一致）になり、ダッシュボードの「版数」「OTA」列が
  実データで機能することを確認した。復帰後`age_s`は数秒、欠測通知は鳴らず。
