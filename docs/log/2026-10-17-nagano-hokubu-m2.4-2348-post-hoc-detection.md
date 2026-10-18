# 2026-10-17 長野県北部M2.4(23:48)の事後解析

`tools/scan_quakes.py`が「投げる価値あり(境界帯)」として挙げた候補。震源要素は
震央N36.6/E137.9・深さ10km・発生23:48・最大震度2。震源距離90km
（M2.4のレンジ52〜104kmの内側、上端寄り）。

## 1. 自動検知の有無

`/events?all=1&size=15`の最新は10/16早朝の既存イベントで、本イベントの10/17 23:48より前。
該当event_idは無し。

## 2. detectlab解析

標準設定（3軸・1-10Hz）:

```
python tools/detectlab.py --at "2026-10-17 23:48:00" \
  --eew "36.6,137.9,10,2026-10-17 23:48" --minutes 10 --device 1 2 --intensity \
  --out docs/log/img/nagano-hokubu-m2.4-8min.png
```

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 1.85 | 1.03/0.50 | 0.97/0.51 | 1.00/0.45 |
| 2 | 2.20 | 1.04/0.42 | 1.02/0.48 | 0.99/0.54 |

閾値4に遠く届かず、全窓でSNR 1.0前後・直線性0.5前後のノイズ水準。機間相関(corr-bin)も
t=20〜40sにfrac 0.37・mean_corr +0.28の単発上昇があるが、直後のt=40〜60sでfrac 0.00・
mean_corr -0.39に落ち、背景(frac 0.14)の範囲を出る持続性が無い。計測震度パネルは両機とも
フラット(I=-0.5/-0.9)。

低帯域・水平2軸（0.5-2Hz、xy）:

```
python tools/detectlab.py --at "2026-10-17 23:48:00" \
  --eew "36.6,137.9,10,2026-10-17 23:48" --minutes 10 --device 1 2 --intensity \
  --band 0.5 2 --axes xy --out docs/log/img/nagano-hokubu-m2.4-lowband-xy.png
```

| device | STA/LTA peak | onset候補 | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|---|
| 1 | 4.05 | t+244.9s（直線性0.72） | 0.91/0.24 | 0.84/0.56 | 1.00/0.56 |
| 2 | 4.39 | t+409.3s（直線性0.61） | 0.99/0.38 | 1.30/0.66 | 0.98/0.58 |

両機とも閾値をわずかに超えるが、onset候補はP窓(t+11-15s)・S窓(t+20-25s)・
コーダ想定域(t+25-205s)のいずれからも外れ、しかも2機で時刻が揃わない(t+245s/t+409s)。
窓内のSNRは0.84〜1.30で背景を上回らず、機間相関も到達窓付近(t=0〜200s)で
frac 0.09〜0.31・背景(0.20)と同水準。低帯域の単発超過は背景ゆらぎで、地震とは無関係と判断する。

device単体プロット（[device1](img/nagano-hokubu-m2.4-device1.png)・
[device2](img/nagano-hokubu-m2.4-device2.png)）にも到達窓付近の過渡は無い。

## 3. 判定

**完全埋没（critical）**。標準・低帯域どちらもP窓・S窓・コーダ想定域のSNR・直線性が
ノイズ水準で、機間相関も背景を持続的に上回らない。震源距離90kmは
[detection_range.md](../detection_range.md)の回帰レンジ(52〜104km)の内側だが、
予測距離に対する比は1.41でレンジ上端寄りだった（同表でM2.9・73km前後も埋没）。
境界帯の埋没側の実例として、`detection_events.csv`に追記して回帰・目安表を再生成した。

新しい知見は`docs/noise.md`の過去事例への追記が要る水準ではないため行わない。

## 4. 保存

`promote_event.py --onset "2026-10-17 23:48:00" --pre 180 --post 600 --verdict critical`で
`0001-59741616`(device1)・`0002-59741616`(device2)を手動保存し、`flag_event.py relate`で
相互リンクした。新規発行直後の書き込みなのでCloudFront invalidationは不要。
