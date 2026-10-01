# 地震候補スキャンの閾値、2回目の定期見直しをした

前回([2026-09-12](2026-09-12-quake-scan-threshold-review.md)、n=6)からの
`tools/detection_events.csv`の増分と、3つの閾値（`FAR_BUT_NOTABLE_MAG`・
`NAMZ_QUAKE_SCAN_WINDOW_HOURS`・`NAMZ_QUAKE_SCAN_STUCK_AFTER_S`）を動かすべきか確認した。

## 「遠すぎ」ゾーンの増分

前回レビュー時点のコミット(8eaa76d)のCSVを復元して`zone_of()`で再判定すると当時は
6件、現在のCSV（42件、うちgood=14件、回帰式は`a=1.2162 b=0.2389`に更新済み）で
再判定すると13件。新たに該当した7件:

| id | M | 震源距離 | 判定 |
|---|---|---|---|
| fukushima-nakadori-m3.3 | 3.3 | 163km | critical |
| miyakejima-oki-m4.3 | 4.3 | 353km | critical |
| tsugaru-kaikyo-m4.5 | 4.5 | 563km | critical |
| chichijima-oki-m4.6 | 4.6 | 1221km | critical |
| miyagi-oki-m4.1 | 4.1 | 323km | critical |
| fukushima-oki-m4.4-1633 | 4.4 | 302km | critical |
| fukushima-oki-m4.2-0445 | 4.2 | 267km | critical |

**全件`critical`。** 成功例（`good`）は前回と変わらず福島県沖M4.0(273km)・
青森県東方沖M4.7(548km)の2件のみ。

## 判断

3つの閾値いずれも変更しない。

- **`FAR_BUT_NOTABLE_MAG`（M≥4.0）**: 新規7件がすべて失敗例（M3.3〜4.6に分布）で、
  成功例は前回から増えていない。閾値を上げる（例: M≥4.5）とM4.0の唯一の成功例を
  取りこぼす。下げる（例: M≥3.5やM≥3.0）としても新規の失敗例が増えるだけで成功例は
  拾えない——九州の群発地震を再流入させるコストに見合う根拠が無い。現状維持。
- **`NAMZ_QUAKE_SCAN_WINDOW_HOURS`（28時間）・`NAMZ_QUAKE_SCAN_STUCK_AFTER_S`（32時間）**:
  DynamoDB `namazu-quake-scan`の`_state`アイテムを確認したところ`last_success_at_us`は
  2026-10-01 09:00:35 JST（本日の実行）を指し、`stuck_notified_at_us`フィールドは
  一度も立っていない（＝停滞検知が一度も発火していない）。`notified_at_us`を持つeid
  群の日付分布を見ても2026-09-11〜10-01の間、実行間隔24時間に対し48時間以上の空白は
  あるが（候補0件の日がまとめて1エントリに現れないだけで実行自体は毎日成功している
  ことは`_state`で担保済み）、重複通知や取りこぼしの不具合報告は無い。約3週間の
  稼働実績が積み上がったが、閾値を動かす根拠になるインシデントはまだ無いので現状維持。

## 次に何が可能になったか

前回確立した「直前レビューのコミットハッシュでCSVを復元→`zone_of()`で再判定→差分を
見る」手順をそのまま流用できた。`tools/detection_range.py`のコード内コメントと
`lambda/quake_scan/handler.py`の`_threshold_reminder()`本文のn数も今回の値(n=13)に
更新済み——次回もこの2箇所を忘れずに合わせること。
