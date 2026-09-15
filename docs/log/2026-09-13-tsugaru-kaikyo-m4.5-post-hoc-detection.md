# 2026-09-13 津軽海峡M4.5 事後解析

## 震源要素

`tools/scan_quakes.py`の候補スキャンより:

- 震央: 津軽海峡 (N41.5/E141.3) 深さ120km
- 発生: 2026-09-13 17:31頃
- マグニチュード: M4.5
- 最大震度: 3
- 震源距離: 563km（レンジ171〜342km。表の上端を大きく超え「恐らく埋没」判定）

## 自動検知の有無

`/events?all=1&size=20`を確認。該当時刻付近の`event_id`なし。閾値未達により正式イベントは立っていない。

## detectlab解析

### 標準設定（1-10Hz・xyz・重ね合わせ）

```
python tools/detectlab.py --at "2026-09-13 17:31:00" --eew "41.5,141.3,120,2026-09-13 17:31" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-13-tsugaru-kaikyo-m4.5-8min.png
```

| 窓 | device1 (SNR/直線性) | device2 (SNR/直線性) |
|---|---|---|
| P窓 | 1.04/0.50 微妙 | 0.96/0.56 微妙 |
| S窓 | 1.03/0.47 微妙 | 1.02/0.57 微妙 |
| コーダ想定域 | 1.00/0.45 微妙 | 1.00/0.56 微妙 |

STA/LTA peak 1.98/2.09（閾値4未達）。機間相関binは背景水準(frac0.15)を明確に超える区間なし。計測震度パネルも両機とも終始震度0付近でフラット。

### 低帯域xy設定（0.5-2Hz）

```
python tools/detectlab.py --at "2026-09-13 17:31:00" --eew "41.5,141.3,120,2026-09-13 17:31" \
  --minutes 10 --device 1 2 --intensity --band 0.5 2 --axes xy \
  --out docs/log/img/2026-09-13-tsugaru-kaikyo-m4.5-lowband-xy.png
```

device2のみSTA/LTA peak=4.19で閾値超過（17:32:40、onset+289s）。ただしdevice1は3.85で未達、該当時刻帯(t=280-300s)の機間相関はfrac=0.00・mean_corr=-0.11で背景(frac0.15)以下。`docs/post_hoc_detection.md`の「片方の機体だけの孤立ピークは機間相関で裏取り」の基準に従い、device2固有ノイズと判断。

### device単体プロット

- [device1](img/2026-09-13-tsugaru-kaikyo-m4.5-device1.png)
- [device2](img/2026-09-13-tsugaru-kaikyo-m4.5-device2.png)

生波形・スペクトログラムにも過渡は見えない。

## 判定

**完全埋没（critical）。** 震源距離563kmはレンジ表の上端を大きく超えており、想定通り埋没した実例。

`0001-<bucket>`/`0002-<bucket>`として手動イベント化・`tools/detection_events.csv`に追記済み。
