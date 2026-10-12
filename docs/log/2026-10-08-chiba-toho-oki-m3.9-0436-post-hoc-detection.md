# 千葉県東方沖M3.9(04:36) 事後解析

## 震源要素

- 発生: 2026-10-08 04:36頃(JST)
- 震央: 千葉県東方沖 N35.6/E140.7、深さ50km
- マグニチュード: 3.9、最大震度2
- 震源距離230km（`detection_range.md`のレンジ118〜236km内の上限寄り。「投げる価値あり(境界帯)」判定だった候補）
- `tools/scan_quakes.py`の定期走査で拾った候補の1つ。同日04:13の千葉県北東部M4.8（[ログ](2026-10-08-chiba-hokutobu-m4.8-0413-post-hoc-detection.md)）の23分後。

## 1. 自動検知の有無

`/events?all=1&size=15`を確認。該当時刻付近に`event_id`なし。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [chiba-toho-oki-m3.9-0436-8min.png](img/chiba-toho-oki-m3.9-0436-8min.png)
- device1単体: [chiba-toho-oki-m3.9-0436-device1.png](img/chiba-toho-oki-m3.9-0436-device1.png)
- device2単体: [chiba-toho-oki-m3.9-0436-device2.png](img/chiba-toho-oki-m3.9-0436-device2.png)
- 低帯域xy: [chiba-toho-oki-m3.9-0436-lowband-xy.png](img/chiba-toho-oki-m3.9-0436-lowband-xy.png)

```
python tools/detectlab.py --at "2026-10-08 04:36" --eew "35.6,140.7,50,2026-10-08 04:36" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/chiba-toho-oki-m3.9-0436-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 1.81 | 0.92/0.36(微妙) | 1.00/0.43(微妙) | 1.02/0.44(微妙) |
| 2 | 2.03 | 0.98/0.58(微妙) | 1.01/0.56(微妙) | 1.10/0.48(微妙) |

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.98 | 0.99/0.62(微妙) | 1.00/0.59(微妙) | 1.29/0.62(微妙) |
| 2 | 3.90 | 0.83/0.60(微妙) | 0.92/0.59(微妙) | 1.43/0.72(要検討) |

標準設定は両機とも閾値のはるか下。低帯域は両機とも閾値4にわずかに届かない(3.98/3.90)が、
重ね合わせ図では発生+90〜110秒付近に両機のSTA/LTAが同時に3前後の山を作り、その後に谷が続く。
`--corr-bin`も同じt=[100,120)sだけ frac0.56・mean+0.44（背景0.14/-0.07）と単発で上がる。
計測震度はdevice2が-0.9→-0.7とわずかに動く程度で、device1は動かない。

## 判定

**微妙／要検討（warning、埋没寄り）。** 同じ時刻に両機の山・機間相関の単発上昇が揃っていて
偶然とは言い切れないが、どれも閾値未満で振幅も計測震度に出ていない。同日の千葉県北東部M4.8
（同じ震央付近、震源距離223km）が標準設定で明瞭に出たのと比べ、Mが0.9小さいこちらは
痕跡が一段弱い。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`chiba-toho-oki-m3.9-0436`として追記
- `promote_event.py`で手動イベント化（`--verdict warning`、onset=発生時刻04:36:00、`--pre 180 --post 600`）
- `flag_event.py relate`で`0001-59713392`・`0002-59713392`を相互リンク
