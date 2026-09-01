# 2026-08-31 福島県中通りM3.3 事後解析

## 震源要素

- 発生: 2026-08-31 18:49頃
- 震央: 福島県中通り N37.1/E140.4 深さ80km
- M3.3　最大震度1
- 震央距離142km・震源距離163km（観測点=湯沢町、`detectlab.py`既定）

`tools/scan_quakes.py --days 3`が直近3日で唯一「投げる価値あり(境界帯)」と拾った候補
（レンジ123〜246km中の下寄り）。他の候補（浦河沖M4.1・熊本群発・奈良県M3.7等）は
いずれも震源距離600km超〜900km超で明確にレンジ外（恐らく埋没・埋没側の実例集め目的
でなければスキップでよい）。

## 自動検知の有無

`/events?all=1&size=20`で確認。該当時刻付近に`event_id`なし（直近の`cloud_confirmed`は
2026-08-30 00:18の震度1イベントで無関係）。手動イベント化もされていない。

## detectlab解析

標準設定（1-10Hz・xyz）:

| | device1 | device2 |
|---|---|---|
| STA/LTA peak | 1.89 | 1.92 |
| P窓 SNR/直線性 | 1.01/0.51 微妙 | 0.97/0.51 微妙 |
| S窓 SNR/直線性 | 1.01/0.36 微妙 | 1.08/0.61 微妙 |
| コーダ想定域 SNR/直線性 | 1.02/0.46 微妙 | 1.02/0.57 微妙 |

低帯域設定（0.5-2Hz・水平xy）:

| | device1 | device2 |
|---|---|---|
| STA/LTA peak | 4.24（onset候補あり） | 3.61（閾値未達） |
| P窓 SNR/直線性 | 1.35/0.58 要検討 | 1.03/0.77 微妙 |
| S窓 SNR/直線性 | 0.91/0.66 微妙 | 1.01/0.55 微妙 |
| コーダ想定域 SNR/直線性 | 1.02/0.58 微妙 | 1.03/0.52 微妙 |

device1の低帯域onset候補（t+56.4s＝18:46:44、発生時刻より前）は`--corr-bin`のt=[40,60)s
binでfrac(corr>=0.6)=0.05・mean_corr=-0.33と背景（frac=0.23・mean_corr=+0.08）を大きく
下回っており、2機の一致が無いので単発ノイズと判断できる。もう1つのonset候補
（t+540.1s、直線性0.67）もt=[540,560)s binがfrac=0.25・mean_corr=+0.09で背景と同水準、
同様にノイズ。

画像:
- 重ね合わせ（標準）: [img/fukushima-nakadori-m3.3-8min.png](img/fukushima-nakadori-m3.3-8min.png)
- 重ね合わせ（低帯域xy）: [img/fukushima-nakadori-m3.3-lowband-xy.png](img/fukushima-nakadori-m3.3-lowband-xy.png)
- device1単体: [img/fukushima-nakadori-m3.3-device1.png](img/fukushima-nakadori-m3.3-device1.png)
- device2単体: [img/fukushima-nakadori-m3.3-device2.png](img/fukushima-nakadori-m3.3-device2.png)

いずれの画像も、P窓・S窓・コーダ想定域の区間だけが目立って立ち上がる様子は無く、
記録区間全体でSTA/LTA比・直線性ともランダムに上下しているだけ。背景と地震到達時刻帯の
分離が標準・低帯域どちらの設定でも付かない。

## 判定

**完全埋没**。震源距離163kmは「投げる価値ありレンジ」123〜246kmの下寄りではあるが、
M3.3という規模の小ささ（`docs/detection_range.md`の学習データでも同程度の距離・
Mでは`ibaraki-nanbu-m3.4`(143km, M3.4)が既にwarning=微妙判定）を踏まえれば妥当な結果。
新しい知見は無く、`docs/noise.md`への追記も無し。
