# 埼玉県南部M3.2(10:32) 事後解析

## 震源要素

- 発生: 2026-10-01 10:32頃(JST)
- 震央: 埼玉県南部 N36.0/E139.5、深さ50km
- マグニチュード: 3.2
- 震源距離131km（`detection_range.md`のレンジ81〜161km内。「投げる価値あり(境界帯)」判定だった候補）
- `tools/scan_quakes.py`の定期走査で拾った候補の1つ。

## 1. 自動検知の有無

`/events?all=1&size=30`を確認。該当時刻付近に`event_id`なし。閾値未達により正式イベントは
立っていない。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [saitama-nanbu-m3.2-1032-8min.png](img/saitama-nanbu-m3.2-1032-8min.png)
- device1単体: [saitama-nanbu-m3.2-1032-device1.png](img/saitama-nanbu-m3.2-1032-device1.png)
- device2単体: [saitama-nanbu-m3.2-1032-device2.png](img/saitama-nanbu-m3.2-1032-device2.png)
- 低帯域xy: [saitama-nanbu-m3.2-1032-lowband-xy.png](img/saitama-nanbu-m3.2-1032-lowband-xy.png)

```
python tools/detectlab.py --at "2026-10-01 10:32" --eew "36.0,139.5,50,2026-10-01 10:32" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/saitama-nanbu-m3.2-1032-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 2.02 | 1.06/0.47(微妙) | 0.98/0.50(微妙) | 1.01/0.45(微妙) |
| 2 | 1.90 | 1.08/0.62(微妙) | 1.08/0.55(微妙) | 1.03/0.54(微妙) |

閾値(4)に遠く届かず、SNR・直線性ともP窓・S窓・コーダ想定域を通じて終始1.0前後・
ノイズと無区別。`--corr-bin`も到達窓付近(t=0〜40s)でfrac 0.05〜0.41と背景(frac 0.11)から
突出した区間は無い。

低帯域設定（0.5-2Hz・水平2軸）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 3.89 | 0.97/0.25(微妙) | 0.93/0.48(微妙) | 1.01/0.59(微妙) |
| 2 | 4.37 | 1.24/0.59(微妙) | 1.02/0.68(微妙) | 1.10/0.60(微妙) |

device2のみ低帯域でSTA/LTA閾値をわずかに超過(4.37)するが、onset候補(10:32:16.85、
t+200.5s)はP窓・S窓・コーダ想定域のどの窓にも対応せず孤立している。対応する
`--corr-bin`のt=[200,220)sはfrac=0.25・mean_corr=-0.00で背景(frac=0.19・mean_corr=+0.01)と
同水準——device2固有ノイズと判断できる。STA/LTA比の重ね描き図を見ても、600秒の記録
全体で閾値(4)前後のピークが到達窓と無関係に何度も散発しており（t=260s・440s・570s付近等）、
到達窓だけが特別に目立つコントラストは無い。

## 判定

**完全埋没。** 標準・低帯域xyどちらもP窓/S窓/コーダ想定域のSNR・直線性が終始ノイズ水準で、
device2の低帯域閾値超過も到達窓と対応せず機間相関にも裏付けが無い。同じ震源距離帯の
2026-09-17 茨城県南部M3.1（完全埋没）と同様のパターン。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`saitama-nanbu-m3.2-1032`として追記
- `promote_event.py`で手動イベント化（`--verdict critical`、onset=発生時刻そのもの、`--pre 180 --post 600`）
- `flag_event.py relate`で相互リンク
