# watchdogのSlack通知にデバイス詳細ページへのリンクを足す

## 何を決めたか

`lambda/watchdog/handler.py`が送る欠測・データ遅延・pull型OTA停滞の通知（と各々の復帰通知）
すべてに、「デバイス」フィールドとしてダッシュボードの`#device/<id>`へのSlack mrkdwnリンクを
追加した。通知を見た時にデバイス番号だけでなく、そのままダッシュボードの詳細ページ
（生存状況・温度トレンド等）へ飛べるようにする。

## なぜそう決めたか

`batch-uplink`の`notify.py`には既に`event_url`/`event_field`（イベント詳細ページへの
リンクを作る同種のヘルパー）があり、detect/ingestの通知で使われている。同じパターンを
デバイス版で足すのが自然だが、`notify.py`は共有ライブラリ側にあり、このプロジェクトの
pinは`v1.8.0`で固定している一方、`batch-uplink`の`master`は既に`v2.4.0`まで進んでいる
（`notify.py`自体は両バージョン間で無変更と確認済み）。ここでpinを上げると、この機能とは
無関係な`Batch`/`Uploader`/`TimeSync`側の変更5バージョン分がまとめて紛れ込み、
CLAUDE.mdが警告する「何も変えていないのに再ビルドで壊れる」の温床になる。

機能自体は`NAMZ_DASHBOARD_URL`環境変数（既に`terraform/main.tf`の`local.lambda_env`で
全Lambda共通に設定済み）とURLパターンの組み立てだけで完結し、`batch-uplink`側の状態
（Batch/Uploaderの実装）に一切依存しない。共有ライブラリを一切変更せず
`lambda/watchdog/handler.py`内にローカルヘルパー`_device_field()`を置くことで、
このタスクのために無関係なバージョン跳躍をする必要をなくした。

## 何が可能になったか

欠測・データ遅延・OTA停滞のSlack通知から、対象デバイスのダッシュボード詳細ページへ
ワンクリックで飛べるようになった。URL形式はダッシュボードの`deviceHash()`
（`dashboard/app.js`）が生成するものと同じ`#device/<id>`（idはゼロ埋めしない生の値）。

pytest（lambda/tests）111件通過。ブラウザでの実地確認はまだ（Slack webhook経由の
実通知確認は次回の欠測イベント発生時 or 手動発火で行う）。
