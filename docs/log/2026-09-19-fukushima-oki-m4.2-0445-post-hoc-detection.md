# 福島県沖M4.2(04:45) 事後解析

## 震源要素

- 発生: 2026-09-19 04:45頃(JST)
- 震央: 福島県沖 N37.0/E141.8、深さ30km
- マグニチュード: 4.2
- 最大震度: 1
- 震源距離267km（`detection_range.md`のレンジ139〜278km内。「投げる価値あり(境界帯)」判定だった候補）

## 1. 自動検知の有無

`/events?all=1&size=30`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [fukushima-oki-m4.2-0445-8min.png](img/fukushima-oki-m4.2-0445-8min.png)
- device1単体: [fukushima-oki-m4.2-0445-device1.png](img/fukushima-oki-m4.2-0445-device1.png)
- device2単体: [fukushima-oki-m4.2-0445-device2.png](img/fukushima-oki-m4.2-0445-device2.png)
- 低帯域xy: [fukushima-oki-m4.2-0445-lowband-xy.png](img/fukushima-oki-m4.2-0445-lowband-xy.png)

```
python tools/detectlab.py --at "2026-09-19 04:45" --eew "37.0,141.8,30,2026-09-19 04:45" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/fukushima-oki-m4.2-0445-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 1.93 | 1.02/0.48(微妙) | 1.00/0.49(微妙) | 1.03/0.43(微妙) |
| 2 | 2.11 | 0.97/0.48(微妙) | 0.98/0.53(微妙) | 1.04/0.52(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.76 | 1.05/0.44(微妙) | 0.98/0.51(微妙) | 1.08/0.57(微妙) |
| 2 | 4.51※ | 1.08/0.55(微妙) | 0.97/0.53(微妙) | 1.23/0.58(微妙) |

※device2低帯域のみSTA/LTA閾値(4)を超過したが、onset候補は04:46:46（発生+299.6秒、
コーダ想定域の外）で直線性0.64と単発。対応する`--corr-bin`のt=280-300s帯はfrac 0.27で
背景(0.21)からわずかな上昇に留まり、孤立した機体固有の揺れと判断。

機間相関（`--corr-bin`）はP窓・S窓・コーダ域いずれの帯でも標準・低帯域とも背景水準
（標準0.22、低帯域0.21）と有意な差がなく、むしろ到達窓中盤（標準t+40〜160s）では
frac≈0.00〜0.06まで沈む区間があり、背景より低かった。

## 判定

**完全埋没（critical）。** 標準・低帯域どちらもSNRが終始1.0前後（ノイズと無区別）、
STA/LTAも標準設定では閾値未達（低帯域device2のみ孤立ピークで超過）、機間相関も到達窓
付近で背景水準を上回らずむしろ沈む区間があった。M4.2・震源距離267kmはレンジ内の
境界帯だったが、実際には検出限界を下回った実例。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`fukushima-oki-m4.2-0445`として追記
- `promote_event.py`で完全埋没でも手動イベント化（`--verdict critical`、`--pre 180 --post 600`）
  → `0001-59658690`（device1）・`0002-59658690`（device2）
- `flag_event.py relate 0001-59658690 0002-59658690`で相互リンク（新規発行直後の続けての
  書き換えのためCloudFront invalidationは不要）
