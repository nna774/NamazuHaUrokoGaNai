# 稼働時間（uptime）・再起動検知を実装した

[docs/uptime.md](../uptime.md)の設計（[前々ログ](2026-08-07-uptime-strategy.md)・
[前ログ](2026-08-07-uptime-header-not-trailer.md)でトレイラー→ヘッダに作り直し済み）を
そのまま実装した。firmware/ingest/api/ダッシュボードの4箇所。

## 何を決めたか

- **firmware**: `X-Namz-Uptime-Us`ヘッダに`esp_timer_get_time()`（起動からのus）を
  毎バッチ乗せる。`kExtraRequestHeaderNames/Values`を2枠に拡張し、`uploaderTask`の
  ループで`gUploader->pump()`を呼ぶ直前に`sUptimeBuf`を`snprintf`で書き換える
  （Uploaderは値をコピーせずポインタを保持するので、送信直前に更新すれば十分）。
- **副産物のバグ修正も同時に実施**: `checkAndPerformPullOta()`のpull型OTA再試行
  バックオフを`millis()`(uint32, 49.7日で折り返す)から`esp_timer_get_time()`(int64, us)
  ベースに置き換えた。他の`millis()`使用箇所（WiFi接続タイムアウト・NTP再同期・
  画面の揺れ表示）は減算パターン＋短い閾値で元々安全なので変更していない。
- **ingest**: `x-namz-uptime-us`ヘッダから`boot_epoch_us = batch_start_us - uptime_us`
  を逆算。リモート再起動/OTAチェックで既に呼んでいた`devices.get_device()`を使い回し、
  追加のDynamoDB読み取り無しで前回値と比較する。判定ロジックは
  `device_meta.should_update_boot_epoch(prev, new) -> bool`という副作用の無い関数に
  切り出した（`devices.evaluate()`と同じ「状態遷移を副作用から分離する」既存パターンに
  倣った。ingest本体には単体テストが無いが、この関数だけはDynamoDBを介さず
  `pytest`で検証できる）。閾値超えの時だけ`device_meta.record_boot_epoch()`で書く。
- **api**: `_device_view()`に`boot_epoch_us`（生値）と`uptime_s`（計算済み秒数、
  `age_s`/`lag_s`と同じ流儀）を追加。
- **ダッシュボード**: デバイス詳細ページの情報テーブルに「稼働時間」行を追加。
  既存の`fmtAgo()`をそのまま流用した。

## なぜそう決めたか

設計（`docs/uptime.md`）は前セッションで固まっていたので、そのまま実装した。
実装中に決めた細部:

- ingestの再起動判定を`device_meta.should_update_boot_epoch()`という独立関数に
  切り出したのは、`_handle_batch`自体がS3/DynamoDBを叩く副作用込みの関数で
  ユニットテストの対象になっていない（このレポにingestのハンドラテストは無い）ため。
  判定ロジックだけでも`devices.evaluate()`と同じ形でテスト可能にしておく方が、
  閾値の妥当性を将来見直す時に安心して変更できる。
- `kExtraRequestHeaderValues`配列は`constexpr`のままだと`sUptimeBuf`（アドレスが
  コンパイル時定数として扱えるか怪しい静的配列）を指せない懸念があったため、
  ドキュメントの当初案どおり`constexpr`を外して`static const char*[]`にした。

## 何が覆ったか

なし。設計どおりに実装した。`docs/uptime.md`は「未着手」から「実装済み（実機・
本番デプロイはまだ）」に更新した。

## 何が可能になったか

- ビルド・テストは通ったので、あとはプロビジョニング済み実機に焼いて動作確認・
  デプロイすれば、デバイス詳細ページに実際の稼働時間が出るようになる。
- `esp_timer_get_time()`ベースの安全な時間比較パターンができたので、今後
  `millis()`由来の折り返しバグを疑う時の直し方の前例になる。

## 動作確認

- `firmware/test/run.sh`: 全通過（NamzWire/Batchのゴールデンテスト。今回のmain.cpp
  変更とは独立だが、既存機能を壊していないことの確認）。
- `pio run`（`esp32dev`・`adxl355`両env）: ビルド成功。
- `pytest lambda/tests`: 97件全通過（`device_meta`の`record_boot_epoch`/
  `should_update_boot_epoch`、apiの`boot_epoch_us`/`uptime_s`表示テストを新規追加）。
- **実機での動作確認・本番デプロイはまだ**（別途、実機に焼いてから行う）。
