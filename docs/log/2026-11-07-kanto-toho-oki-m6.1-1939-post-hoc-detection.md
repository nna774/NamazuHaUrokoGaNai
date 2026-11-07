# 2026-11-06 関東東方沖 M6.1（19:39）の事後解析

「さっきの地震」を受けた解析。自動検知が両機で立っていたので、答え合わせ・コーダ終端確認・
相互リンク・verdict付与が主な作業。

## 震源要素（気象庁 `list.json`）

- 発生 2026-11-06 19:39（分丸め。秒は公表されない）、関東東方沖 N35.0/E142.2、深さ10km、M6.1、最大震度3
- 観測点からの震央距離372km・震源距離373km（detectlab出力）

## 自動検知

- `0001-59798721`（device1、onset 19:40:59.35、震度1.2 / 1.65gal）
- `0002-59798721`（device2、onset 19:40:59.44、震度1.2 / 1.60gal）
- 両機とも `cloud_confirmed`、device1はデバイス速報も出ていた。`related_events` は空だったので
  `flag_event.py relate` で相互リンク、`verdict good` を付与、`/event?id=` 2件をinvalidation
  （確定済みで取得され得たため）

## detectlab

分丸め（19:39:00）基準のままだとP窓がSNR 0.97/1.00の「微妙」になった。onset候補（P相当）は
19:40:20なので、P走時を約55秒と見て**推定発生を19:39:25に置き**、`--eew-estimated`付きで
全図を撮り直した（onsetに合わせて置いたので、推定基準の窓SNRはある程度循環している点に注意。
ただしこの置き方はS窓にも整合している）。

推定発生19:39:25基準・標準設定（3軸・1-10Hz）。STA/LTA peakは10.72 / 12.06（閾値4の約3倍）:

| | device1 | device2 |
|---|---|---|
| P窓 SNR / 直線性 | 3.12 / 0.90 | 4.04 / 0.91 |
| S窓 SNR / 直線性 | 7.37 / 0.82 | 9.71 / 0.82 |
| コーダ想定域 SNR / 直線性 | 3.07 / 0.77 | 4.01 / 0.79 |

機間相関（20秒bin、背景frac 0.16）は推定発生+60秒から立ち上がり、+60〜120秒で
frac 0.97〜0.98、+140〜160秒で0.78、+180〜200秒で0.35、+200秒以降は背景水準に戻った。

**コーダ終端の確認:** 保存範囲（onset+600秒=19:51頃）の先にコーダは残っていない。
分丸め基準で`--minutes 20`と通しで撮った図でも、相関は発生+220秒でほぼ背景に戻り、
以降は+820秒（19:52:40頃）に孤立した1binが0.54に立つのみ。連続性が無く、
別の短い擾乱と見て延長はしない。

図: [20min重ね描き（推定基準）](img/kanto-toho-oki-m6.1-1939-20min-est.png) /
[device1](img/kanto-toho-oki-m6.1-1939-device1-est.png) /
[device2](img/kanto-toho-oki-m6.1-1939-device2-est.png)。
比較用の分丸め基準: [20min](img/kanto-toho-oki-m6.1-1939-20min.png) /
[device1](img/kanto-toho-oki-m6.1-1939-device1.png) /
[device2](img/kanto-toho-oki-m6.1-1939-device2.png)

## 判定

**probable detection（good）。** 自動確定が両機で立ち、P窓・S窓・コーダ想定域のすべてが両機で
「地震らしい」、STA/LTAは閾値の約3倍、機間相関は到達窓で背景の約6倍。気象庁の最大震度3に
対し自機は震度1で、震源距離373kmの減衰として妥当。

## 作業

- `flag_event.py relate`・`verdict good`・CloudFront invalidation（`/event?id=`を2件のみ、
  ワイルドカードなし）を実施
- `tools/detection_events.csv`に追記、`docs/detection_range.md`を再生成
- 手違い: AWS_PROFILE未設定のworktreeからdetectlabを呼ぶと既定プロファイルのMFA入力待ちで
  `EOFError`になる。worktreeでは`AWS_PROFILE=namazu-admin`を明示すること
