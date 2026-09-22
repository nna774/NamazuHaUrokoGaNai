# 福島県沖M4.5(07:30) 事後解析

## 震源要素

- 発生: 2026-09-22 07:30頃(JST)
- 震央: 福島県沖 N37.5/E142.1、深さ30km
- マグニチュード: 4.5
- 最大震度: 1
- 震源距離299km（`detection_range.md`のレンジ164〜327km内。「投げる価値あり(境界帯)」判定だった候補）

## 1. 自動検知の有無

`/events?all=1&size=20`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [fukushima-oki-m4.5-0730-8min.png](img/fukushima-oki-m4.5-0730-8min.png)
- device1単体: [fukushima-oki-m4.5-0730-device1.png](img/fukushima-oki-m4.5-0730-device1.png)
- device2単体: [fukushima-oki-m4.5-0730-device2.png](img/fukushima-oki-m4.5-0730-device2.png)
- 低帯域xy: [fukushima-oki-m4.5-0730-lowband-xy.png](img/fukushima-oki-m4.5-0730-lowband-xy.png)

```
python tools/detectlab.py --at "2026-09-22 07:30" --eew "37.5,142.1,30,2026-09-22 07:30" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/fukushima-oki-m4.5-0730-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 2.04 | 1.02/0.42(微妙) | 1.08/0.39(微妙) | 1.02/0.43(微妙) |
| 2 | 1.89 | 1.00/0.49(微妙) | 1.12/0.41(微妙) | 1.04/0.51(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 4.08※ | 1.05/0.47(微妙) | 1.19/0.54(微妙) | 1.15/0.61(微妙) |
| 2 | 4.45※ | 0.94/0.49(微妙) | 1.42/0.57(要検討) | 1.28/0.69(微妙) |

※両機とも低帯域xyでSTA/LTA閾値(4)を超過。device1のonset候補は07:29:21(発生+161.5s、
コーダ想定域内)で直線性0.32、device2は07:30:54(発生+240.1s、同じくコーダ想定域内)で
直線性0.37と、いずれも単発ピークで直線性が低い。`--corr-bin`で対応する帯を見ると、
device1のt+161.5s付近(t=[160,180)s)はfrac=0.13(背景0.18並み)、device2のt+240.1s付近
(t=[240,260)s)はfrac=0.33/mean_corr=+0.31とやや高いが、対応する時刻にdevice1側の
上昇が無く孤立している。S窓でdevice2のみSNR1.42/直線性0.57と「要検討」域に入るが、
対応するbin(t=[60,80)s frac=0.26、t=[80,100)s frac=0.21)は背景(0.18)よりわずかに高い
程度で決定的ではない。

## 判定

**完全埋没（critical）。** 標準設定はP窓・S窓・コーダ想定域いずれもSNRが1.0前後でノイズと
無区別、STA/LTAも閾値未達。低帯域xyでは両機ともSTA/LTA閾値を超えるが、onset候補の直線性が
低く(0.29〜0.37)、機間相関も対応する時刻に両機同時の上昇が見られない孤立ピーク。S窓での
device2の「要検討」も相関的な裏付けが弱く、2026-09-14福島県沖M4.4-1633・2026-09-19
福島県沖M4.2-0445と同様のパターン（単発の低帯域STA/LTA超過はあるが機体固有ノイズ）と判断。
M4.5・震源距離299kmはレンジ内の境界帯だったが、実際には検出限界を下回った実例。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`fukushima-oki-m4.5-0730`として追記
- `promote_event.py`で完全埋没でも手動イベント化（`--verdict critical`、`--pre 180 --post 600`）
  → `0001-59667660`（device1）・`0002-59667660`（device2）
- `flag_event.py relate 0001-59667660 0002-59667660`で相互リンク（新規発行直後の続けての
  書き換えのためCloudFront invalidationは不要）
