# 福島県会津M2.9(08:46) 事後解析

## 震源要素

- 発生: 2026-09-25 08:46頃(JST)
- 震央: 福島県会津 N37.4/E139.4、深さ10km
- マグニチュード: 2.9
- 最大震度: 1
- 震源距離74km（`detection_range.md`のレンジ68〜137km内。「投げる価値あり(境界帯)」判定だった候補）

## 1. 自動検知の有無

`/events?all=1&size=50`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [2026-09-25-aizu-fukushima-m2.9-8min.png](img/2026-09-25-aizu-fukushima-m2.9-8min.png)
- device1単体: [2026-09-25-aizu-fukushima-m2.9-device1.png](img/2026-09-25-aizu-fukushima-m2.9-device1.png)
- device2単体: [2026-09-25-aizu-fukushima-m2.9-device2.png](img/2026-09-25-aizu-fukushima-m2.9-device2.png)
- 低帯域xy: [2026-09-25-aizu-fukushima-m2.9-lowband-xy.png](img/2026-09-25-aizu-fukushima-m2.9-lowband-xy.png)

```
python tools/detectlab.py --at "2026-09-25 08:46:00" --eew "37.4,139.4,10,2026-09-25 08:46" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-25-aizu-fukushima-m2.9-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 1.99 | 0.91/0.50(微妙) | 0.96/0.39(微妙) | 0.99/0.44(微妙) |
| 2 | 2.06 | 1.05/0.58(微妙) | 0.97/0.53(微妙) | 1.02/0.52(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 4.26※ | 0.96/0.31(微妙) | 0.98/0.65(微妙) | 1.03/0.55(微妙) |
| 2 | 3.78 | 0.90/0.35(微妙) | 0.97/0.53(微妙) | 1.04/0.55(微妙) |

※device1のみ低帯域xyでSTA/LTA閾値(4)を超過。onset候補は08:55:52(発生+約592s、P窓・S窓・
コーダ想定域のいずれよりも大きく後ろ)で直線性0.74。`--corr-bin`で対応する帯(t=[580,600)s)を
見るとfrac=0.17・mean_corr=+0.09で、背景(0.21/-0.00)と同水準。到達窓から大きく外れた時刻・
かつ相関的な裏付けも無いため、device1固有の孤立ノイズと判断する。device2は同設定でも
閾値未達(3.78)のまま。

機関相関（`--corr-bin`、低帯域xy）は到達窓に対応するt=[0,20)s: frac=0.35、t=[-20,0)s: frac=0.18
など背景(0.21)からわずかに上下する程度で、他の無関係な時間帯(t=[-160,-140)s: frac=0.38、
t=[280,300)s: frac=0.34等)にも同水準以上の揺れがあり、到達窓だけが際立って高いという
パターンは見られない。

## 判定

**完全埋没（critical）。** 標準・低帯域xyともP窓・S窓・コーダ想定域のSNRが終始0.9〜1.0台で
ノイズと無区別。低帯域xyでdevice1のみSTA/LTA閾値を超えるが、onset候補の時刻が到達窓から
大きく外れ、対応する機間相関も背景水準に留まるため孤立ノイズと判断。M2.9・震源距離74kmは
レンジ内の境界帯だったが、実際には検出限界を下回った実例。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`aizu-fukushima-m2.9-0846`として追記
- `promote_event.py`で完全埋没でも手動イベント化（`--verdict critical`、`--pre 180 --post 600`）
  → `0001-59676452`（device1）・`0002-59676452`（device2）
- `flag_event.py relate 0001-59676452 0002-59676452`で相互リンク（新規発行直後の続けての
  書き換えのためCloudFront invalidationは不要）
