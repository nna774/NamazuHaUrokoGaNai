# 2026-08-06 リモート再起動を実装した

## 何を決めたか

[docs/remote_restart.md](remote_restart.md)（[2026-08-06 設計ログ](2026-08-06-remote-restart-design.md)）
の設計通りに実装した。

- batch-uplink（別リポジトリ）に `devices.request_restart`/`clear_restart_request`と、
  `Uploader` の `watchResponseHeader` オプトインを追加し、
  [PR#3](https://github.com/nna774/batch-uplink/pull/3) をマージして `v1.3.0` タグを切った
- このレポは `v1.3.0` へpin（`firmware/platformio.ini` / `terraform/build_lambda.sh` 両方）
- `lambda/ingest/handler.py` の `_handle_batch` で再起動要求をレスポンスヘッダへ反映
- `tools/request_restart.py`（`request`/`cancel`/`list` サブコマンド）を新設
- `firmware/src/main.cpp` の `uploaderTask` に安全な再起動シーケンスを実装

## なぜそう決めたか

batch-uplink は他プロジェクト(Electabuzz)と共有するリポジトリのため、そちらへの
PRマージ・タグ切りは自動モードの分類器にブロックされた。ユーザーに確認を取ってから
進めた。

## 何が覆ったか

設計ドキュメントでは `request_restart(device_id)` としていたが、実装時に
`mark_offline_notified` 等の既存API（`at_us` を引数に取る）に合わせて
`request_restart(device_id, at_us)` にした。細部の具体化であり方針の変更ではない。

## 次に何が可能になったか

`python tools/request_restart.py request <device_id>` で実機に対して再起動要求を
出せる。**実機での動作確認はまだ**（firmwareビルド[esp32dev/adxl355両env成功]・
`pytest lambda/tests tools/tests`[111件パス]は確認済み）。次にやるなら実機で
1台に要求を立て、次回バッチ送信で再起動されること・watchdog Lambdaの欠測通知が
鳴らないこと（30〜40秒で復帰）を確認する。
