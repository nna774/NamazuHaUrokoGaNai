# 福島県沖M4.1(10-07 09:22) 事後解析

## 震源要素

- 発生: 2026-10-07 09:22頃(JST)
- 震央: 福島県沖 N37.0/E141.1、深さ60km
- マグニチュード: 4.1、最大震度2
- 震源距離211km（`detection_range.md`のレンジ132〜263km内。「投げる価値あり(境界帯)」判定だった候補）
- `tools/scan_quakes.py`の定期走査で拾った候補の1つ。

## 1. 自動検知の有無

`/events?all=1&size=15`を確認。該当時刻付近に`event_id`なし。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [fukushima-oki-m4.1-0922-8min.png](img/fukushima-oki-m4.1-0922-8min.png)
- device1単体: [fukushima-oki-m4.1-0922-device1.png](img/fukushima-oki-m4.1-0922-device1.png)
- device2単体: [fukushima-oki-m4.1-0922-device2.png](img/fukushima-oki-m4.1-0922-device2.png)
- 低帯域xy: [fukushima-oki-m4.1-0922-lowband-xy.png](img/fukushima-oki-m4.1-0922-lowband-xy.png)

```
python tools/detectlab.py --at "2026-10-07 09:22" --eew "37.0,141.1,60,2026-10-07 09:22" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/fukushima-oki-m4.1-0922-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.70 | 0.98/0.37(微妙) | 0.98/0.47(微妙) | 1.11/0.48(微妙) |
| 2 | 4.37 | 1.02/0.49(微妙) | 1.01/0.60(微妙) | 1.21/0.54(微妙) |

標準設定ではdevice2のみ僅かに閾値超過（onset候補09:23:36.7、直線性0.84）。

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 5.97 | 1.06/0.54(微妙) | 0.93/0.52(微妙) | 1.55/0.69(**地震らしい**) |
| 2 | 8.14 | 0.99/0.53(微妙) | 0.89/0.65(微妙) | 1.90/0.78(**地震らしい**) |

低帯域では両機ともSTA/LTA閾値を明確に超過し、onset候補は device1=09:23:37.0・
device2=09:23:29.4〜09:23:45.3（発生+90〜105秒）で時刻が揃う。計測震度も両機が同じ
タイミング(発生+95秒付近)で階段状に立ち上がった（I=-0.3、震度0相当）。STA/LTAは山の後に
LTA汚染の谷が続く地震らしい形。

一方、`--corr-bin`の機間相関は t=[80,120)sで frac0.30〜0.46・mean+0.26〜+0.35 と上がるものの、
この記録は**背景自体が高め**（frac0.28・mean+0.15）で、背景比の突出は小さい。
2026-10-02茨城県南部M3.9のような「記録全体で唯一の突出した山」ほどの一致ではない。

## 判定

**微妙／要検討（warning、弱いprobable寄り）。** 両機が同タイミングで低帯域STA/LTA閾値を超え、
計測震度も同時に立ち上がっているが、3点セット（device2閾値超過＋device1同時上昇＋機間相関上昇）
のうち機間相関が背景比で明確に分離できていない。埋没とは言い切れないが、probable detectionと
断言する根拠にも欠ける。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`fukushima-oki-m4.1-0922`として追記
- `promote_event.py`で手動イベント化（`--verdict warning`、onset=09:23:30、`--pre 300 --post 600`）
- `flag_event.py relate`で`0001-59711087`・`0002-59711087`を相互リンク
