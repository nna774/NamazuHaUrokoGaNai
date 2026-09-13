# 2026-09-13 富山県東部M2.9 事後解析

## 震源要素

`tools/scan_quakes.py`の候補スキャンより:

- 震央: 富山県東部 (N36.4/E137.6) 深さ0km
- 発生: 2026-09-13 01:03頃
- マグニチュード: M2.9
- 最大震度: 1
- 震源距離: 123km（レンジ73〜146km。境界帯で「投げる価値あり」判定）

## 自動検知の有無

`/events?all=1&size=20`を確認。該当時刻付近の`event_id`なし。閾値未達により正式イベントは立っていない。

## detectlab解析

### 標準設定（1-10Hz・xyz・重ね合わせ）

```
python tools/detectlab.py --at "2026-09-13 01:03" --eew "36.4,137.6,0,2026-09-13 01:03" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-13-toyama-tobu-m2.9-8min.png
```

| 窓 | device1 (SNR/直線性) | device2 (SNR/直線性) |
|---|---|---|
| P窓 | 1.02/0.51 微妙 | 1.04/0.53 微妙 |
| S窓 | 1.05/0.45 微妙 | 1.07/0.72 微妙 |
| コーダ想定域 | 1.00/0.45 微妙 | 1.01/0.53 微妙 |

STA/LTA peak 1.80/1.78（閾値4未達）。機間相関binも該当時間帯で背景水準(frac0.19-0.21程度)を明確に超えない。計測震度パネルは両機とも終始フラット。

### 低帯域xy設定（0.5-2Hz）

```
python tools/detectlab.py --at "2026-09-13 01:03" --eew "36.4,137.6,0,2026-09-13 01:03" \
  --minutes 10 --device 1 2 --intensity --band 0.5 2 --axes xy \
  --out docs/log/img/2026-09-13-toyama-tobu-m2.9-lowband-xy.png
```

device2のみSTA/LTA peak=4.90で閾値超過（01:04:10、S窓〜コーダ想定域境界、t≈70s、直線性0.87）。device1は3.42で未達。該当時間帯(t=60-80s)の機間相関はfrac=0.26・mean_corr=+0.09で背景(frac0.21・mean+0.02)よりわずかに高い程度に留まり、`docs/post_hoc_detection.md`の基準（機間相関が背景を明確に上回るか）で見ると有意な裏付けとは言えない。device2固有ノイズと判断。

### device単体プロット

- [device1](img/2026-09-13-toyama-tobu-m2.9-device1.png)
- [device2](img/2026-09-13-toyama-tobu-m2.9-device2.png)

生波形・スペクトログラムにも過渡は見えない。

## 判定

**完全埋没（critical）。** 震源距離123kmはレンジ表の境界帯だが、実際には検出限界を下回った。境界帯・埋没側の実例として`docs/detection_range.md`の回帰データに追加する価値がある。

`0001-<bucket>`/`0002-<bucket>`として手動イベント化・`tools/detection_events.csv`に追記済み。
