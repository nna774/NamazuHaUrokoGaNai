# 2026-09-10 福島県会津M3.2 事後解析

## きっかけ

ユーザーからtenki.jpの地震詳細ページURL
（`http://bousai.tenki.jp/bousai/earthquake/detail-20260910185532.html`）を渡され、
「これ取れてるかな」の調査依頼。

## 震源要素（tenki.jp、`tools/tenki_view.py --dry-run`で抽出）

- 発生: 2026-09-10 18:55頃、気象庁発表18:58
- 震源: 福島県会津 N37.0/E139.4、深さ「ごく浅い」（`tenki_view.py`の慣例値10km扱い）、M3.2
- 最大震度3: 福島県檜枝岐村
- 震央距離52km・震源距離53km（`--eew "37.0,139.4,10,2026-09-10 18:55:00"`）

[2026-09-03の福島県会津M3.5](2026-09-03-fukushima-aizu-m3.5-post-hoc-detection.md)
（N37.2/E139.3・震源距離53km・probable detection）とほぼ同じ震源位置・同距離で、
Mだけ0.3小さい事例。

M3.2の「投げる価値ありレンジ」77〜154kmに対し震源距離53kmはレンジより近く、
目安上は「ほぼ確実に捕れている」側だが、[群馬県北部M3.2](2026-08-29-gunma-kitabu-m3.2-post-hoc-detection.md)
（44km・warning）の前例もあり、近距離小Mだからといって確定検知が保証されるわけではない。

## 自動検知の有無

`/events?all=1&size=20`で確認、直近イベントは2026-09-06（青森県東方沖M4.7の事後解析等）で、
9/10 18:55付近に自動検知イベントは無い。

## detectlab解析

### 標準設定（3軸・1-10Hz）

| 項目 | device1 | device2 |
|---|---|---|
| STA/LTA peak | 2.16 | 2.41 |
| onset候補 | なし（閾値4未達） | なし（閾値4未達） |
| P窓(18:55:06-08) SNR/直線性 | 1.04/0.37 微妙 | 1.03/0.52 微妙 |
| S窓(18:55:11-15) SNR/直線性 | 0.98/0.42 微妙 | 1.08/0.53 微妙 |
| コーダ想定域(18:55:15-18:58:15) SNR/直線性 | 1.02/0.45 微妙 | 1.05/0.53 微妙 |

`--corr-bin`（20秒bin、閾値0.6）では、t=[60,80)s（frac=0.32・mean_corr=+0.22）と
t=[120,140)s（frac=0.41・mean_corr=+0.29）が背景（frac=0.12・mean_corr=-0.04）を明確に
上回った。device単体プロットでも両機ともコーダ想定域内（発生+40秒付近）にSTA/LTA~2.1-2.4の
小さな山が同時に立っており、閾値には遠く届かないが偶然の一致にしては両機の形が揃っている。

### 低帯域・水平2軸（0.5-2Hz, xy）

| 項目 | device1 | device2 |
|---|---|---|
| STA/LTA peak | 3.81 | 4.17（onset候補: 発生+137.4秒、直線性0.77） |
| P窓 SNR/直線性 | 1.40/0.67 要検討 | 0.89/0.42 微妙 |
| S窓 SNR/直線性 | 1.00/0.62 微妙 | 1.27/0.35 微妙 |

device2は閾値をわずかに超えたが、時刻（発生+137秒）はP窓・S窓・コーダ想定域のいずれからも
外れており、`--corr-bin`の同時間帯（t=[120,140)s）のfracは0.18で背景(0.19)と同水準——
device1との機間相関は上がっていない。[docs/post_hoc_detection.md](../post_hoc_detection.md)の
「片方だけの孤立ピークは`--corr-bin`で裏取りする」に従うと、この閾値超過はdevice2固有ノイズと
判断できる（標準設定側で両機一致した60-140秒帯のピークとは別物）。

画像: [8分重ね合わせ図(標準)](img/2026-09-10-fukushima-aizu-m3.2-8min.png)、
[低帯域xy重ね合わせ図](img/2026-09-10-fukushima-aizu-m3.2-lowband-xy.png)、
[device1単体](img/2026-09-10-fukushima-aizu-m3.2-device1.png)、
[device2単体](img/2026-09-10-fukushima-aizu-m3.2-device2.png)。

## 判定: 微妙／要検討（warning）

STA/LTAは両機とも閾値4に届かず（標準2.16/2.41、低帯域3.81/4.17も時刻がずれ機間相関も
上がらないためノイズと判断）、P窓・S窓も両機ともSNR~1.0で単独では判定できない。
一方で標準設定のコーダ想定域内、t=60-140秒帯で両機のSTA/LTAが同時に小さな山を作り、
直線性の機間相関binも背景を明確に上回る——[2026-09-03の会津M3.5](2026-09-03-fukushima-aizu-m3.5-post-hoc-detection.md)
で見られた「固定窓では微妙・コーダ内の一致で判定を上げる」パターンと同型だが、
STA/LTAのピーク高さ（今回2.1-2.4 vs 会津M3.5の7.2-10.3、閾値比で1/3程度）・機間相関の
ピーク値（今回frac0.41 vs 会津M3.5のfrac0.41だが会津M3.5は2分ズームでfrac0.63まで上がる）
ともに明らかに弱く、同じ「probable」と呼ぶには根拠が薄い。M3.2はM3.5より地震のエネルギーが
約1/3であることを踏まえると、埋没ぎりぎりまで弱くなっているのは物理的に妥当。

JMA計測震度換算はI=-0.4/-0.7（いずれも震度0）で自動確定閾値には遠く届かない。

## 手動イベント化・相互リンク

`tools/promote_event.py --onset "2026-09-10 18:55:00" --pre 180 --post 600 --verdict warning`
でdevice1・device2それぞれ永久保存（onsetは検知できなかったため発生時刻そのものを使用）。

- `0001-59634470`（device1）: I=-0.4、peak=0.265gal
- `0002-59634470`（device2）: I=-0.7、peak=0.199gal

`tools/flag_event.py relate 0001-59634470 0002-59634470`で相互リンク。新規発行直後の
relateのためCloudFront invalidationは不要。

## 実行環境メモ

worktreeには`aws` CLI本体・`.envrc`が無かった。本体チェックアウトの`.venv`
（`/Users/nana/codes/NamazuHaUrokoGaNai/.venv/bin/python3`）と、`~/.aws/config`の
`[profile namazu-admin]`（`namazu-admin`ロールをassume、MFA不要）を`AWS_PROFILE=namazu-admin`で
指定して`detectlab.py`・`promote_event.py`を実行した。rawバケット名は
`namazu-data-486414336274`を直接指定（`docs/post_hoc_detection.md`の「worktreeから実行する時の
注意」の通り）。

## 次に可能になったこと

- この地震の波形はダッシュボードから確認できる状態になった。
- `tools/detection_events.csv`に1行追記(verdict=warning)、`docs/detection_range.md`を再生成した。
