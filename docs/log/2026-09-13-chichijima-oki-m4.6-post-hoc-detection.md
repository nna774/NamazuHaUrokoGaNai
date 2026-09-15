# 2026-09-13 父島近海M4.6 事後解析

## 震源要素

`tools/scan_quakes.py`の候補スキャンより:

- 震央: 父島近海 (N26.5/E142.9) 深さ10km
- 発生: 2026-09-13 12:50頃
- マグニチュード: M4.6
- 最大震度: 1
- 震源距離: 1221km（レンジ180〜360kmを大きく超え「恐らく埋没」判定）

## 自動検知の有無

`/events?all=1&size=20`を確認。該当時刻付近の`event_id`なし。閾値未達により正式イベントは立っていない。

## detectlab解析

### 標準設定（1-10Hz・xyz・重ね合わせ）

```
python tools/detectlab.py --at "2026-09-13 12:50:00" --eew "26.5,142.9,10,2026-09-13 12:50" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-13-chichijima-oki-m4.6-8min.png
```

| 窓 | device1 (SNR/直線性) | device2 (SNR/直線性) |
|---|---|---|
| P窓 | 1.02/0.44 微妙 | 1.03/0.59 微妙 |
| S窓 | 1.00/0.44 微妙 | 1.01/0.56 微妙 |
| コーダ想定域 | 1.00/0.44 微妙 | 1.01/0.58 微妙 |

STA/LTA peak 2.00/1.84（閾値4未達）。機間相関binはP窓後半にあたるt=180-200sでfrac=0.43・mean_corr=+0.37と背景(frac0.07)より一時的に高い区間があるが、単発bin（前後のbinは背景並みに戻る）でSTA/LTA・SNRとも同時刻に上昇していないため、地震性の一致とは判断しない。計測震度パネルも両機とも終始震度0付近でフラット。

### 低帯域xy設定（0.5-2Hz）

```
python tools/detectlab.py --at "2026-09-13 12:50:00" --eew "26.5,142.9,10,2026-09-13 12:50" \
  --minutes 10 --device 1 2 --intensity --band 0.5 2 --axes xy \
  --out docs/log/img/2026-09-13-chichijima-oki-m4.6-lowband-xy.png
```

STA/LTA peak 3.45/3.48でともに閾値未達。P窓・S窓のSNR/直線性も標準設定と同水準（1.0〜1.1 / 0.5〜0.6）でノイズ域を出ない。

### device単体プロット

- [device1](img/2026-09-13-chichijima-oki-m4.6-device1.png)
- [device2](img/2026-09-13-chichijima-oki-m4.6-device2.png)

生波形・スペクトログラムにも過渡は見えない。

## 判定

**完全埋没（critical）。** 震源距離1221kmはレンジ表を大きく超えており、想定通り埋没した実例。

`0001-<bucket>`/`0002-<bucket>`として手動イベント化・`tools/detection_events.csv`に追記済み。
