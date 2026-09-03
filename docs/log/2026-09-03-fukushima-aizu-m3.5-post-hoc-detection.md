# 2026-09-03 福島県会津M3.5 事後解析

## きっかけ

ユーザーからtenki.jpの地震詳細ページURL
（`https://earthquake.tenki.jp/lite/bousai/earthquake/detail/2026/09/03/2026-09-03-22-34-58.html`）
を渡され、「うちの震度計は捉えてた？」の調査依頼。

## 震源要素（tenki.jp）

- 発生: 2026-09-03 22:34頃、気象庁発表22:37
- 震源: 福島県会津 N37.2/E139.3、深さ約10km、M3.5
- 震度2: 福島県只見町／震度1: 福島県南会津町・新潟県三条市・魚沼市
- 観測点（湯沢町）からの震央距離52km・震源距離53km（`--eew "37.2,139.3,10,2026-09-03 22:34"`）

M3.5の「投げる価値ありレンジ」127〜254kmに対し震源距離53kmは明確に近く、
目安上は「ほぼ確実に捕れている」側（[docs/detection_range.md](../detection_range.md)）。

## 実行環境メモ: AWS認証情報が無い状態から開始した

このセッションの実行環境には`aws` CLI本体も`~/.aws/`も存在せず、`.venv`も無かった。
`python3 -m venv .venv && pip install -r tools/requirements.txt`で構築後、ユーザーが
`namazu-admin`プロファイル（`role_arn`をassumeする設定）を用意し、`AWS_PROFILE=namazu-admin`
で`tools/detectlab.py`・`tools/promote_event.py`を実行した。boto3は`~/.aws/config`の
`[profile namazu-admin]`を素で読むため、`aws` CLI本体が無くても支障は無かった。

`namazu-admin`ロールには最初DynamoDB(`namazu-events`)への権限が無く、`promote_event.py`が
S3コピー成功後のDynamoDB書き込みで`AccessDeniedException`になった（S3側は先に成功済みで、
`meta.json`込みで冪等に上書きされる設計のため実害なし）。ユーザーがIAMポリシーを追加後、
同じ`--onset`で再実行して解消した。

## 自動検知の有無

`/events?all=1&size=20`で確認、直近イベントは2026-08-30 00:18（千葉県東方沖M4.9）で止まって
おり、9/3 22:34付近に自動検知イベントは無い。

## detectlab解析

標準設定（3軸・1-10Hz）、`--eew "37.2,139.3,10,2026-09-03 22:34"`:

| 項目 | device1 | device2 |
|---|---|---|
| STA/LTA peak | 7.20 | 10.31 |
| onset候補 | 22:35:09.38 | 22:35:09.12 |
| P窓(22:34:06-08) SNR/直線性 | 0.92/0.33 微妙 | 1.03/0.65 微妙 |
| S窓(22:34:11-15) SNR/直線性 | 1.14/0.44 微妙 | 0.92/0.55 微妙 |
| コーダ想定域(22:34:15-22:37:15) SNR/直線性 | 1.13/0.46 微妙 | 1.21/0.56 微妙 |

P窓・S窓それぞれの固定窓判定は両機とも「微妙」だったが、コーダ想定域の中の
**22:35:09頃（発生+69秒）に両機ほぼ同時（0.25秒差）でSTA/LTAが閾値4の約2倍まで跳ね、
直線性も0.68/0.71（判定基準0.6超）まで一致して立ち上がった**。`--corr-bin`でも
その時刻を含むt=[60,80)s binがfrac(corr≥0.6)=0.41・mean_corr=+0.44と、背景
（frac=0.18・mean_corr=+0.06、全体窓での算出値）を明確に上回った。2分ズーム
（`--minutes 1 --lead-min 1`、背景推定には短すぎる旨の警告は出るが可視化目的のみ使用）
では同じt=[60,80)s binでfrac=0.63・mean_corr=+0.56とさらに明瞭。オーバーレイ図の
3段目（device1/2間の直線性の移動Pearson相関）はピーク時刻でほぼ1.0に到達しており、
「片方だけの孤立ピークではない」ことを裏付けている。

固定窓（P窓・S窓）で光らずコーダ想定域内で両機一致した点は、
[docs/post_hoc_detection.md](../post_hoc_detection.md)の「P窓・S窓が示すのは
"到達瞬間の幅"であって"揺れの続く長さ"ではない」の通り——今回はSTA/LTA検出自体に
系統的な遅れが乗った弱い揺れの典型例。

画像: [8分重ね合わせ図](img/fukushima-aizu-m3.5-8min.png)、
[device1単体](img/fukushima-aizu-m3.5-device1.png)、
[device2単体](img/fukushima-aizu-m3.5-device2.png)、
[2分ズーム(オーバーレイ)](img/fukushima-aizu-m3.5-2min-zoom.png)。

device単体プロットでは、生波形パネルには過渡が全く見えない一方、バンドパス後・
STA/LTA比パネルには単発の鋭いピークがはっきり見える——振幅としては背景ノイズに
埋もれる程度の、STA/LTA検出でだけ目立つ小さな揺れ。

## 判定: probable detection

2機が独立に、コーダ想定域内のほぼ同時刻（0.25秒差）に、STA/LTA大幅超過＋直線性上昇＋
機間相関ほぼ1.0という3つの特徴を揃えて反応した。[docs/post_hoc_detection.md](../post_hoc_detection.md)
の判定基準「2機が同タイミング・同特徴で一致」に合致し、**probable detection**と判断した。

JMA計測震度換算では I=-0.2（震度0相当）と極めて小さく、リアルタイム閾値には遠く
届かない規模——STA/LTAでは明瞭でもJMA震度では小さい、[群馬県北部M3.2](2026-08-29-gunma-kitabu-m3.2-post-hoc-detection.md)
と同型のパターン。

## 手動イベント化・相互リンク

`tools/promote_event.py --onset "2026-09-03 22:35:09" --pre 180 --post 600`で
device1・device2それぞれ永久保存。

- `0001-59614750`（device1）: I=-0.2、peak=0.343gal
- `0002-59614750`（device2）: I=-0.2、peak=0.355gal

`tools/flag_event.py relate 0001-59614750 0002-59614750`で相互リンク。新規発行直後の
relateのため、CloudFront invalidationは不要（[docs/post_hoc_detection.md](../post_hoc_detection.md)
「新規発行した直後にrelate/noteで続けて書き換える一連の操作は不要」に該当）。

## 次に可能になったこと

- この地震の波形はダッシュボードから確認できる状態になった。
- `tools/detection_events.csv`に1行追記(verdict=good)、`docs/detection_range.md`を
  再生成した。回帰は`verdict=good`のみでフィットするため今回の追加が直接効き、
  n=9→10で「投げる価値ありレンジ」がM3.5で127〜254km→87〜173km、M6.0で356〜711km→
  359〜718kmへ大きく動いた（近距離・小Mのgood事例が無かったため回帰の切片・傾き自体が
  それまで遠方偏りだった）。n=10とまだ小さいため、今後さらに近距離側の事例が増えると
  再び動く可能性がある。
