# 2026-11-06 福島県沖 M4.3 の事後解析(警告: 微妙〜弱いprobable)

「投げる価値あり(境界帯)」の通知を受けて解析した。同震源域の
[2026-09-14 福島県沖M4.3(20:00)](2026-09-14-fukushima-oki-m4.3-2000-post-hoc-detection.md)(これもwarning)に続く境界帯の事例。

## 震源要素

- 2026-11-06 03:05(JST・分単位)、福島県沖 M4.3、深さ80km、(37.8, 141.5)、最大震度2
- 震源距離268km(M4.3のレンジ145〜290kmの上端付近)

## 自動検知

`/events?all=1`に該当時刻のイベントなし。

## detectlab

分丸め(03:05:00)基準の標準設定は両機平坦だったが、低帯域xyで両機のonsetが発生+120秒に揃い、
分丸めの窓より後ろだった。**onsetに引きずられて推定発生を03:05:50に置いた**(丸めの範囲内
+50秒。onsetに合わせて選んだので、以下の推定基準のS窓の数値はある程度循環している点に注意)。
`--eew-estimated`付きで全図を撮り直した。

分丸め基準・標準設定(3軸1-10Hz。比較用: [8min](img/fukushima-oki-m4.3-1106-8min.png)):

| | STA/LTA peak | P窓 SNR | S窓 SNR | コーダ想定域 SNR |
|---|---|---|---|---|
| device1 | 2.05 | 0.98 | 1.00 | 1.08 |
| device2 | 2.91 | 0.97 | 1.02 | 1.15 |

低帯域xy(0.5-2Hz)・分丸め基準: STA/LTA peak 4.01/6.81。onset候補は両機とも03:07:01
(device1 03:07:01.83・device2 03:07:00.94、時刻差約0.9秒、直線性0.91/0.94)。
device2には発生+約650秒(03:12:41)にもう1つ候補があるが孤立している。

推定発生03:05:50基準・低帯域xy([図](img/fukushima-oki-m4.3-1106-lowband-xy.png)):

| | P窓 SNR/直線性 | S窓 SNR/直線性 | コーダ想定域 SNR/直線性 |
|---|---|---|---|
| device1 | 1.33/0.59 | 2.45/0.70 地震らしい | 1.11/0.58 |
| device2 | 1.58/0.30 | 3.37/0.75 地震らしい | 1.22/0.59 |

標準設定でもS窓は1.37/1.54で「要検討」。機間相関(`--corr-bin`、推定基準・低帯域xy)は
+60〜100秒でfrac 0.36/0.38(背景0.19)。

- 重ね描き: [8min-est](img/fukushima-oki-m4.3-1106-8min-est.png)
- device単体: [device1](img/fukushima-oki-m4.3-1106-device1.png)・[device2](img/fukushima-oki-m4.3-1106-device2.png)
- 低帯域xy: [lowband-xy](img/fukushima-oki-m4.3-1106-lowband-xy.png)

## 判定

**warning**。両機onsetの時刻一致(約0.9秒)・直線性0.9超・推定基準のS窓が両機で地震らしい、の
3点は揃うが、いずれも弱い。機間相関の上昇は背景の約2倍止まりで、別binにも0.37〜0.39の揺らぎが
ある。計測震度は両機とも-0.4/-0.6(震度0)で、S窓で段が上がる程度。device1のSTA/LTA 4.01は
閾値ぎりぎり(device2の方が高感度である点と整合)。good(probable)にするには根拠が足りない。

## 作業

- `promote_event.py --verdict warning`で永久保存(onsetは推定発生03:05:50、`--pre 180 --post 600`)。
  event_idは`0001-59796731`・`0002-59796731`。`flag_event.py relate`で相互リンク済み。
  新規発行直後なのでCloudFront invalidationは不要。
- `tools/detection_events.csv`に追記、`docs/detection_range.md`を再生成。
- 手違い: 最初の`relate`でevent_idを推測して打ち「イベントが見つからない」で失敗(書き込み前に
  弾かれたので実害なし)。昇格出力のevent_idをそのまま使うこと。
