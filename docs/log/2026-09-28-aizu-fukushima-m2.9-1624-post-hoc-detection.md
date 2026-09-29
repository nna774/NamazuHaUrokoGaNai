# 福島県会津M2.9(16:24) 事後解析

3日前の[2026-09-25 08:46の同震央(N37.4/E139.4)付近M2.9](2026-09-25-aizu-fukushima-m2.9-0846-post-hoc-detection.md)
と同一地点での再発。

## 震源要素

- 発生: 2026-09-28 16:24頃(JST)
- 震央: 福島県会津 N37.4/E139.4、深さ0km
- マグニチュード: 2.9
- 最大震度: 1
- 震源距離73km（`detection_range.md`のレンジ68〜137km内。「投げる価値あり(境界帯)」判定だった候補）

## 1. 自動検知の有無

`/events?all=1&size=50`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [2026-09-28-aizu-fukushima-m2.9-1624-8min.png](img/2026-09-28-aizu-fukushima-m2.9-1624-8min.png)
- device1単体: [2026-09-28-aizu-fukushima-m2.9-1624-device1.png](img/2026-09-28-aizu-fukushima-m2.9-1624-device1.png)
- device2単体: [2026-09-28-aizu-fukushima-m2.9-1624-device2.png](img/2026-09-28-aizu-fukushima-m2.9-1624-device2.png)
- 低帯域xy: [2026-09-28-aizu-fukushima-m2.9-1624-lowband-xy.png](img/2026-09-28-aizu-fukushima-m2.9-1624-lowband-xy.png)

```
python tools/detectlab.py --at "2026-09-28 16:24:00" --eew "37.4,139.4,0,2026-09-28 16:24" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-28-aizu-fukushima-m2.9-1624-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 2.92 | 0.98/0.50(微妙) | 1.06/0.44(微妙) | 1.03/0.48(微妙) |
| 2 | 1.98 | 0.98/0.46(微妙) | 1.01/0.48(微妙) | 1.00/0.50(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.16 | 0.94/0.41(微妙) | 0.94/0.51(微妙) | 1.05/0.60(微妙) |
| 2 | 4.27※ | 1.19/0.77(微妙) | 1.03/0.69(微妙) | 0.98/0.59(微妙) |

※device2のみ低帯域xyでSTA/LTA閾値(4)を超過。onset候補は16:25:01.6(発生+約62s、コーダ想定域
内)で直線性0.70。`--corr-bin`で対応する帯(t=[60,80)s)を見るとfrac=0.11で、背景(0.20)より
むしろ低い。到達に対応する時刻に両機同時の上昇が無いため、device2固有の孤立ノイズと判断する。

機間相関は到達窓付近(t=[0,20)s: 0.17、t=[-20,0)s: 0.22)も背景(0.20)と同水準で、地震らしい
上昇は見られない。

## 判定

**完全埋没（critical）。** 標準・低帯域xyともP窓/S窓/コーダ想定域のSNRが終始0.9〜1.2台で
ノイズと無区別。低帯域xyでdevice2のみSTA/LTA閾値を超えるが、対応する機間相関が背景以下
のため孤立ノイズと判断。3日前の同震央M2.9(08:46・深さ10km・震源距離74km)と同じく検出限界
を下回った実例。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`aizu-fukushima-m2.9-1624`として追記
- `promote_event.py`で完全埋没でも手動イベント化（`--verdict critical`、`--pre 180 --post 600`）
  → `0001-59686008`（device1）・`0002-59686008`（device2）
- `flag_event.py relate 0001-59686008 0002-59686008`で相互リンク（新規発行直後の続けての
  書き換えのためCloudFront invalidationは不要）
