# 2026-11-20 最新イベントの探索をscan 1ページに依存しない形にする

## 発端

Electabuzz で、`namazu-events` と同じ作りのイベントテーブルが2026-09-30に1000件を超えたあと、
続いている逸脱がバッチごとに新規セッションとして記録・通知されるようになった
（Electabuzz `81cc2e5` で修正済み）。こちらの `lambda/common/events.py` も同じ形だった。

- `_latest_event()` が `scan(Limit=1000)` の1ページ目だけから最新イベントを探している。
  ingest の速報と detect の確定報が両方ここを通るので、1000件を超えると揺れが割れて通知が増える。
- `recent_events()` も1ページ目だけを読んでいた。`event_backfill` がこれを使うので、
  1000件を超えると最近のイベントの波形バックフィルが黙って漏れる。

2026-11-20時点で385件・月50件前後の増加。1000件到達は2027年秋ごろの見込みで、実害はまだ無い。

## 決めたこと

- Electabuzz と同じく、**デバイスごとの最新イベントを指すポインタ項目**（`event_id = "latest#0001"`、
  属性 `latest_event_id`）を同じテーブルに置き、`GetItem` で引く。ポインタが無い・指す先が
  消えている時だけ全件 scan で探して作り直す。GSI を使わないので terraform 変更も埋め戻しも不要
  （初回の書き込みで自動的に作られる）。
  - Electabuzz はデバイス×イベント種別ごとだが、こちらは種別が無いのでデバイスごと。
- **ポインタは無条件には進めない。** WiFi断のあとファームがバックフィルすると、過去の onset が
  新規セッションとして作られることがある。旧実装は `last_us` 最大を最新としていたので、その意味を
  保つため、書いた項目の `last_us` がポインタの指す先以上の時だけ向け直す。
  `record_manual_event`（`promote_event.py`）も旧実装では最新判定の候補に入っていたので、同じ条件で進める。
- `recent_events()` は `_scan_all()` に寄せた。全件 scan の費用（バッチ到着ごと）は残るが、
  385件・約136KBなので今は問題にしない。
- 全件 scan 系（`events._scan_all()` と `tools/flag_event.py` の `_scan_all()`）はポインタ項目を除外する。
  `flag_event.py` は `_device_of()` で event_id を数値分解するため、除外しないと `relate --before`
  等で落ちる。API の `/event` は id の書式検査でポインタ id を弾くので変更不要。

## 気づいたが触っていないこと

`record_cloud_detection()` の `newly_confirmed` は、`_record` が `prev` をそのまま書き換えるため、
先に速報があるセッションでは常に False になる。呼び出し側（detect）はこの値を使っていないので実害は無い。

## デプロイ（2026-11-20 15:11）

PR #273 マージ後に5関数とも terraform apply（差分は `source_code_hash` のみ）。
直後に `/events`（既定・`all=1`）が385件をポインタ混入なしで返し、device 1・2 の受信も継続していることを確認した。
ポインタ項目は次の速報/確定報で初めて作られるので、apply 時点ではまだ無い。
`namazu-admin` ロールには CloudWatch Logs・メトリクスの読み取り権限が無く、detect/ingest のエラー有無は直接は見ていない。
