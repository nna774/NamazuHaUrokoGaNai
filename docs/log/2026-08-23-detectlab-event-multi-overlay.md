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

## 動作確認

`0001-59577127`/`0002-59577127`で3パターン確認した:

```bash
# 保存済み範囲のみ（軽い）
python detectlab.py --event 0001-59577127 0002-59577127 --out overlay.png
# raw/を都度取り直し(--minutes/--lead-min分)
python detectlab.py --event 0001-59577127 0002-59577127 --from-raw --minutes 10 --out overlay.png
```

いずれも`--at`+`--device 1 2`で手動onset指定した場合と同じ形の図（STA/LTA・直線性・
一致度の3段）が出ることを確認した。既存の`pytest tools/tests`（14件）・
`pytest lambda/tests tools/tests`（204件）は無変更で通過。

## 残課題

`tools/README.md`の「プレースホルダー」節（`#128`）は、onset時刻を手で引いて
`--at`に渡す暫定手順だった。今回`--event`が複数受け付けられるようになったので
不要になった——`#128`のマージ判断・整理はユーザーに委ねる。
