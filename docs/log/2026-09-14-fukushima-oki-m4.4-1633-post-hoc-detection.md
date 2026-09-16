# 2026-09-14 福島県沖M4.4(16:33) 事後解析

## 震源要素

`tools/scan_quakes.py`の候補スキャンより:

- 震央: 福島県沖 (N37.2/E142.2) 深さ20km
- 発生: 2026-09-14 16:33頃
- マグニチュード: M4.4
- 最大震度: 1
- 震源距離: 302km（レンジ162〜324km。境界帯）

## 自動検知の有無

`/events?all=1&size=20`を確認。該当時刻付近の`event_id`なし。閾値未達により正式イベントは立っていない。

## detectlab解析

### 標準設定（1-10Hz・xyz・重ね合わせ）

```
python tools/detectlab.py --at "2026-09-14 16:33:00" --eew "37.2,142.2,20,2026-09-14 16:33" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-09-14-fukushima-oki-m4.4-1633-8min.png
```

| 窓 | device1 (SNR/直線性) | device2 (SNR/直線性) |
|---|---|---|
| P窓 | 0.97/0.45 微妙 | 1.02/0.62 微妙 |
| S窓 | 1.04/0.45 微妙 | 1.05/0.48 微妙 |
| コーダ想定域 | 1.03/0.47 微妙 | 1.04/0.53 微妙 |

STA/LTA peak 1.91/1.91（閾値4未達）。機間相関binもS窓〜コーダ帯(t=60-100s)でfrac 0.07〜0.19と
背景(frac0.15)並みで超過なし。

### 低帯域xy設定（0.5-2Hz）

```
python tools/detectlab.py --at "2026-09-14 16:33:00" --eew "37.2,142.2,20,2026-09-14 16:33" \
  --minutes 10 --device 1 2 --intensity --band 0.5 2 --axes xy \
  --out docs/log/img/2026-09-14-fukushima-oki-m4.4-1633-lowband-xy.png
```

device2のみSTA/LTA peak=4.83で閾値超過（onset候補16:34:32/16:34:35、コーダ想定域内 t+273〜276s）。
device1は3.89で未達。`docs/post_hoc_detection.md`の「片方の機体だけの孤立ピークは機間相関で裏取り」の
基準に従い該当binを確認したところ、t=[260,280)s frac=0.14・mean_corr=-0.13で背景(frac0.22)以下——
device2固有ノイズと判断。S窓はdevice2のみ「要検討」（SNR=1.38/直線性=0.54）だが、対応する
t=[60,80)/[80,100)sの機間相関もfrac 0.15/0.27と背景並みで、両機一致の裏付けは無い。

### device単体プロット

- [device1](img/2026-09-14-fukushima-oki-m4.4-1633-device1.png)
- [device2](img/2026-09-14-fukushima-oki-m4.4-1633-device2.png)

## 判定

**完全埋没（critical）。** 震源距離302kmはレンジ表の境界帯だが、実際にはSTA/LTA・SNR・直線性の
どの指標も両機一致の地震らしい上昇を示さず、device2低帯域の閾値超過も機間相関の裏付けが無く
固有ノイズと判断した。境界帯・埋没側の実例として記録する。

`0001/0002-59645706`として手動イベント化・`tools/detection_events.csv`に追記済み。
