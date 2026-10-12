# 茨城県北部M4.0(07:14) 事後解析

## 震源要素

- 発生: 2026-10-08 07:14頃(JST)
- 震央: 茨城県北部 N36.5/E140.6、深さ60km
- マグニチュード: 4.0、最大震度3
- 震源距離177km（`detection_range.md`のレンジ125〜249km内。「投げる価値あり(境界帯)」判定だった候補）
- `tools/scan_quakes.py`の定期走査で拾った候補の1つ。

## 1. 自動検知の有無

`/events?all=1&size=15`を確認。該当時刻付近に`event_id`なし。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [ibaraki-hokubu-m4-0714-8min.png](img/ibaraki-hokubu-m4-0714-8min.png)
- device1単体: [ibaraki-hokubu-m4-0714-device1.png](img/ibaraki-hokubu-m4-0714-device1.png)
- device2単体: [ibaraki-hokubu-m4-0714-device2.png](img/ibaraki-hokubu-m4-0714-device2.png)
- 低帯域xy: [ibaraki-hokubu-m4-0714-lowband-xy.png](img/ibaraki-hokubu-m4-0714-lowband-xy.png)

```
python tools/detectlab.py --at "2026-10-08 07:14" --eew "36.5,140.6,60,2026-10-08 07:14" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/ibaraki-hokubu-m4-0714-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 2.31 | 0.96/0.55(微妙) | 1.13/0.35(微妙) | 1.08/0.42(微妙) |
| 2 | 2.12 | 1.00/0.49(微妙) | 1.25/0.38(微妙) | 1.12/0.46(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 4.22 | 0.76/0.53(微妙) | 1.72/0.69(**地震らしい**) | 1.32/0.65(要検討) |
| 2 | 4.50 | 0.85/0.49(微妙) | 2.25/0.84(**地震らしい**) | 1.81/0.69(**地震らしい**) |

標準設定は両機とも閾値未達。低帯域ではS窓で両機とも「地震らしい」判定になり、device2の
onset候補(07:14:47.5、直線性0.94)はS窓(07:14:39-50)の中。計測震度も両機が発生+45〜70秒で
同時に小さな階段(device1 -0.4、device2 -0.6)を作る。

ただし**STA/LTA閾値超過のピーク時刻そのものは到達と無関係**: device1の4.22は
07:21:24(発生+444秒)、device2の2つ目のonset候補は07:22:23(発生+503秒)で、
いずれもコーダ想定域の外の孤立ピーク。肝心の機間相関も、S窓に当たるt=[40,60)sは
frac0.08・mean-0.20（背景0.21/-0.03）と**むしろ背景以下**で、t=[60,80)sがfrac0.30/mean+0.14と
わずかに上がる程度。なお`--corr-bin`の最終bin(t=[600,620)s)のfrac1.00は
データ終端(07:24:00)を過ぎた端の見かけで、評価に使っていない。

## 判定

**微妙／要検討（warning）。** S窓で両機のSNR・直線性が上がり、計測震度も両機で同時に動くが、
機間相関が背景を上回らず、閾値超過ピークは到達と無関係な時刻にある。3点セット（device2閾値超過＋
device1同時上昇＋機間相関上昇）のうち機間相関が欠けているため、probable detectionまでは
上げない。完全埋没とも言い切れない境界線上。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`ibaraki-hokubu-m4-0714`として追記
- `promote_event.py`で手動イベント化（`--verdict warning`、onset=発生時刻07:14:00、`--pre 180 --post 600`）
- `flag_event.py relate`で`0001-59713708`・`0002-59713708`を相互リンク
