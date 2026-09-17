# 茨城県南部M3.1(06:11) 事後解析

## 震源要素

- 発生: 2026-09-17 06:11頃(JST)
- 震央: 茨城県南部 N36.1/E139.9、深さ50km
- マグニチュード: 3.1
- 最大震度: 1
- 震源距離143km（`detection_range.md`のレンジ76〜153km内。「投げる価値あり(境界帯)」判定だった候補）

## 1. 自動検知の有無

`/events?all=1&size=30`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [ibaraki-nanbu-m3.1-0611-8min.png](img/ibaraki-nanbu-m3.1-0611-8min.png)
- device1単体: [ibaraki-nanbu-m3.1-0611-device1.png](img/ibaraki-nanbu-m3.1-0611-device1.png)
- device2単体: [ibaraki-nanbu-m3.1-0611-device2.png](img/ibaraki-nanbu-m3.1-0611-device2.png)
- 低帯域xy: [ibaraki-nanbu-m3.1-0611-lowband-xy.png](img/ibaraki-nanbu-m3.1-0611-lowband-xy.png)

```
python tools/detectlab.py --at "2026-09-17 06:11" --eew "36.1,139.9,50,2026-09-17 06:11" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/ibaraki-nanbu-m3.1-0611-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 2.05 | 1.06/0.55(微妙) | 1.00/0.51(微妙) | 1.02/0.43(微妙) |
| 2 | 2.12 | 1.02/0.65(微妙) | 0.95/0.54(微妙) | 1.01/0.53(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.89 | 0.86/0.61(微妙) | 1.01/0.51(微妙) | 1.00/0.56(微妙) |
| 2 | 4.05※ | 1.06/0.66(微妙) | 1.13/0.63(微妙) | 1.01/0.53(微妙) |

※device2低帯域のみSTA/LTA閾値(4)を超えたが、onset候補は06:16:49（発生+531秒、
コーダ想定域の外）で直線性0.34と低く、`docs/post_hoc_detection.md`が言う「片方だけの
孤立ピーク」に該当する。

機間相関（`--corr-bin`）はP窓・S窓・コーダ域いずれの帯でも標準設定frac 0.17〜0.22、
低帯域frac 0.13〜0.17で、背景水準（標準0.22、低帯域0.17）と有意な差がなかった。

## 判定

**完全埋没（critical）。** 標準・低帯域どちらもSNRが終始1.0前後（ノイズと無区別）、
機間相関も到達窓付近で背景水準を上回らなかった。M3.1・震源距離143kmはレンジ内の
境界帯だったが、実際には検出限界を下回った実例。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`ibaraki-nanbu-m3.1-0611`として追記
- `promote_event.py`で完全埋没でも手動イベント化（`--verdict critical`、`--pre 180 --post 600`）
  → `0001-59653102`（device1）・`0002-59653102`（device2）
- `flag_event.py relate 0001-59653102 0002-59653102`で相互リンク（新規発行直後の続けての
  書き換えのためCloudFront invalidationは不要）
