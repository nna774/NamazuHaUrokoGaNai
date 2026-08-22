# detectlab.pyの`--event`を複数指定できるようにし、`--from-raw`を追加する

## 背景

`0001-59577127`/`0002-59577127`の重ね描き図を出す際、`--event`は単一event_idしか
受け付けず複数機重ね描みは`--at`+`--device`限定だったため、event_idから
onset時刻をDynamoDBで手引きしてJSTに変換するひと手間が要った
（[2026-08-23の`tools/README.md`プレースホルダー追記](2026-08-23-event-post-window-extension.md)
はこの手間を埋めるための暫定対応だった）。「detectlabをいじれば複数device渡せるように
ならないか」「範囲も、付けた時だけrawを引くとかできないか」という指摘を受け、
`--event`自体を拡張することにした。

## 対応

- **`--event`を`nargs="+"`に変更**。1つなら従来通り単独表示、2つ以上なら
  `--at`+`--device`と同じ重ね描き（STA/LTA・直線性・2機なら一致度パネル）になる。
  device idは各event_idの先頭4桁から機械的に決まるので`--device`は不要。
- **`--from-raw`を追加**。既定では`events/<id>/`の保存済み範囲をそのまま読む
  （軽い・保持期限を過ぎたイベントでも見られる）。指定すると各event_idの
  `meta.json`から`onset_us`を読み、`raw/`を`--minutes`/`--lead-min`ぶん都度
  取り直す（保存範囲を超えて見たい時。raw保持期間内でのみ有効）。
- `--at`側の重ね描きループと`--event`側の重ね描きループで「解析→レポート→dump→
  `plot_overlay`向けタプル化」の処理が完全に同じだったため、`overlay_source()`
  ヘルパーに切り出して共有した。
- **`--event`に裸のバケット番号（event_idの`-`より後ろ、例`59577127`）を渡せる
  ようにした。** `expand_event_ids()`が`--device`と組んで`0001-59577127`のような
  完全なevent_idへ展開する。同一地震なら関連イベントは大抵同じ30秒バケットに
  乗る（`events.event_id`のバケット幅）ので、`--event 59577127 --device 1 2`
  だけで済むことが多い。`-`を含む値（既に完全なID）はそのまま通すので、バケットが
  ズレている機体だけ完全なIDを個別に書いて混在させられる。

## 動作確認

`0001-59577127`/`0002-59577127`で4パターン確認した:

```bash
# 保存済み範囲のみ（軽い）
python detectlab.py --event 0001-59577127 0002-59577127 --out overlay.png
# raw/を都度取り直し(--minutes/--lead-min分)
python detectlab.py --event 0001-59577127 0002-59577127 --from-raw --minutes 10 --out overlay.png
# 裸のバケット番号+--deviceで完全IDを自動展開
python detectlab.py --event 59577127 --device 1 2 --out overlay.png
```

いずれも`--at`+`--device 1 2`で手動onset指定した場合と同じ形の図（STA/LTA・直線性・
一致度の3段）が出ることを確認した。`expand_event_ids()`のユニットテスト3件を追加。
`pytest tools/tests`（17件）・`pytest lambda/tests tools/tests`（207件）が通過。

## 経緯（`#128`について）

`tools/README.md`に一度「プレースホルダー」節（`#128`）を追記したが、それは
onset時刻を手で引いて`--at`に渡す暫定手順だった。本対応で`--event`が複数・
裸のバケット番号を受け付けられるようになり不要になったため、`#128`はクローズし
プレースホルダーの記載は本PRへ引き継いだ。
