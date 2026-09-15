# 2026-09-13 三宅島近海M4.3 事後解析

## 震源要素

`tools/scan_quakes.py`の候補スキャンより:

- 震央: 三宅島近海 (N33.8/E139.4) 深さ20km
- 発生: 2026-09-13 04:18頃
- マグニチュード: M4.3
- 最大震度: 2
- 震源距離: 353km（レンジ235〜470km。表の上端寄りで「恐らく埋没」判定）

## 自動検知の有無

`/events?all=1&size=20`を確認。該当時刻付近の`event_id`なし（一覧の直近は2026-09-10までの既存イベントのみ）。閾値未達により正式イベントは立っていない。

## detectlab解析

### 標準設定（1-10Hz・xyz・重ね合わせ）

```
python tools/detectlab.py --at "2026-09-13 04:18" --eew "33.8,139.4,20,2026-09-13 04:18" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-13-miyakejima-m4.3-8min.png
```

| 窓 | device1 (SNR/直線性) | device2 (SNR/直線性) |
|---|---|---|
| P窓 | 1.02/0.46 微妙 | 0.97/0.60 微妙 |
| S窓 | 0.98/0.52 微妙 | 1.00/0.59 微妙 |
| コーダ想定域 | 1.00/0.45 微妙 | 1.01/0.57 微妙 |

STA/LTA peak 1.80/2.03（閾値4未達）。機間相関binは全区間で背景水準(frac0.16)を明確に超える区間なし。計測震度パネルも両機とも終始震度0付近でフラット。

### 低帯域xy設定（0.5-2Hz）

```
python tools/detectlab.py --at "2026-09-13 04:18" --eew "33.8,139.4,20,2026-09-13 04:18" \
  --minutes 10 --device 1 2 --intensity --band 0.5 2 --axes xy \
  --out docs/log/img/2026-09-13-miyakejima-m4.3-lowband-xy.png
```

device1のみSTA/LTA peak=4.40で閾値超過（04:22:16、コーダ想定域終端付近）。ただしdevice2は3.66で未達、該当時刻帯(t=240-260s)の機間相関はfrac=0.24・mean_corr≈0で背景(frac0.16程度)と有意に区別できず。`docs/post_hoc_detection.md`の「片方の機体だけの孤立ピークは機間相関で裏取り」の基準に従い、device1固有ノイズと判断。

### device単体プロット

- [device1](img/2026-09-13-miyakejima-m4.3-device1.png)
- [device2](img/2026-09-13-miyakejima-m4.3-device2.png)

生波形・スペクトログラムにも過渡は見えない。

## 判定

**完全埋没（critical）。** 震源距離353kmはレンジ表の上端寄りで、想定通り埋没した実例。

`0001-<bucket>`/`0002-<bucket>`として手動イベント化・`tools/detection_events.csv`に追記済み。
