# 栃木県北部M2.7(17:21) 事後解析

## 震源要素

- 発生: 2026-09-16 17:21頃(JST)
- 震央: 栃木県北部 N36.8/E139.4、深さ0km
- マグニチュード: 2.7
- 最大震度: 2
- 震源距離54km（`detection_range.md`のレンジ61〜123kmを下回り「近すぎ・ほぼ確実に捕れる」
  判定だった候補）

## 1. 自動検知の有無

`/events?all=1&size=30`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [tochigi-hokubu-m2.7-1721-8min.png](img/tochigi-hokubu-m2.7-1721-8min.png)
- device1単体: [tochigi-hokubu-m2.7-1721-device1.png](img/tochigi-hokubu-m2.7-1721-device1.png)
- device2単体: [tochigi-hokubu-m2.7-1721-device2.png](img/tochigi-hokubu-m2.7-1721-device2.png)
- 低帯域xy: [tochigi-hokubu-m2.7-1721-lowband-xy.png](img/tochigi-hokubu-m2.7-1721-lowband-xy.png)

```
python tools/detectlab.py --at "2026-09-16 17:21" --eew "36.8,139.4,0,2026-09-16 17:21" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/tochigi-hokubu-m2.7-1721-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 1.83 | 1.01/0.43(微妙) | 0.95/0.40(微妙) | 1.00/0.44(微妙) |
| 2 | 2.34 | 1.04/0.65(微妙) | 0.99/0.61(微妙) | 1.03/0.55(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.27 | 1.10/0.70(微妙) | 1.01/0.63(微妙) | 1.07/0.52(微妙) |
| 2 | 3.36 | 1.00/0.74(微妙) | 1.05/0.75(微妙) | 0.98/0.57(微妙) |

両設定ともSTA/LTAは閾値(4)未達。機間相関（`--corr-bin`）は標準設定でfrac 0.13〜0.21
（背景0.13）、低帯域でも同水準で、到達窓付近に有意な上昇は見られなかった。

## 判定

**完全埋没（critical）。** 震源距離54kmと近く「ほぼ確実に捕れる」目安レンジの内側
だったが、M2.7という規模の小ささが上回り、標準・低帯域どちらもノイズと無区別だった。
「近距離＝検出容易」とは限らない実例として`docs/detection_range.md`のレンジ推定に
残す価値がある。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`tochigi-hokubu-m2.7-1721`として追記
- `promote_event.py`で完全埋没でも手動イベント化（`--verdict critical`、`--pre 180 --post 600`）
  → `0001-59651562`（device1）・`0002-59651562`（device2）
- `flag_event.py relate 0001-59651562 0002-59651562`で相互リンク（新規発行直後の続けての
  書き換えのためCloudFront invalidationは不要）
