# events/<id>/meta.json が弱い再発火で上書きされるバグを直す

## 背景

[POST_SECONDS延長の調査](2026-08-23-event-post-window-extension.md)中に見つけた別件。

`lambda/detect/handler.py`の`_confirm()`は、揺れが検知閾値を継続して超えている間
stride(30秒)ごとに再発火し、そのたびに`_put_meta()`が呼ばれる。`_put_meta()`は
`s3.put_object`で`events/<id>/meta.json`を**無条件に上書き**しており、セッション内の
最大値を保持する仕組みが無かった。

M5.9イベント(`0001-59580602`)の実データで確認：DynamoDB側の`confirmed_intensity`
（`events._record`がセッション内max集計している権威値）は2.6〜2.7だったが、S3の
`meta.json`は`max_intensity=0.8`になっていた。地震の後半、振幅が弱まったcodaでの
再発火が`_put_meta()`を再度呼び、弱い値でセッション最大の記録を消していた。

## 対応

`_put_meta()`に、書き込み前に既存の`meta.json`を読んで最大/最小値へマージする
`_merge_meta()`を追加した:

- `max_intensity`・`peak_gal`・`a0_gal`は**既存値との最大値**を残す
  （`events.py`の`_record`が`max_intensity`/`peak_gal`をmax集計しているのと同じ方針）。
- `onset_us`は**既存値との最小値**を残す（セッションの真の起点を保持）。
- 既存の`meta.json`が無い(初回)場合はそのまま素通し。

純粋関数`_merge_meta`として切り出し、S3を叩かずにユニットテストできるようにした
（`lambda/tests/test_detect_meta_merge.py`）。

## 影響範囲

- 影響するのは`_confirm()`経由（自動確定）で複数回`_put_meta`が呼ばれるイベントのみ。
  `_preserve_prompt_waveforms`経由（速報のみの確定判定）は1回しか呼ばれないため
  実害は無かったが、`_put_meta`自体の修正なので恩恵は受ける。
- `promote_event.py`（手動昇格）は別関数で直接`s3.put_object`しており対象外。
- 過去に既に上書きされてしまった`meta.json`（`0001-59580602`等）はこの修正では直らない。
  別途バックフィルで直す。
