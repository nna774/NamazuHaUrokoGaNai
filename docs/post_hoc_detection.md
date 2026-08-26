# 地震通知を受けての事後解析手順

「〇〇地震、うちの震度計は捉えてた？」と聞かれた時の標準手順。
[2026-08-24 浦河沖M6.0の事後解析](log/2026-08-24-urakawa-oki-m6.0-post-hoc-detection.md)で
実際にやった手順を一般化したもの。判断に迷った点や新しい知見が出たら、このファイル自体を
更新して洗練させていくこと（手順書は使うたびに直す前提）。

## 0. 起点: 震源要素を確定させる

以下のどちらかから、**震源要素（緯度・経度・深さ・マグニチュード・発生時刻）** と、
できれば**各地の震度一覧**を得る。

- **tenki.jpの地震詳細ページURL**（例:
  `https://earthquake.tenki.jp/bousai/earthquake/detail/YYYY/MM/DD/YYYY-MM-DD-HH-MM-SS.html`）。
  WebFetchで「震源要素（緯度・経度・深さ・マグニチュード・発生時刻・気象庁発表時刻）と
  各地の震度をすべて」を聞く。
- **気象庁電文形式のテキスト**（ユーザーが直接貼ることがある）。例:
  ```
  2026/08/23 22:45:06 第1報 (2026/08/23 22:44:55発生)震央:N41.8/E143.0(浦河沖)深さ30km 最大:M6.1 震度4
  ```
  緯度・経度・深さ・マグニチュード・発生時刻をその場でパースする。「第1報」は速報値で
  後の確定報と数値がズレることがある点に注意。

**発生時刻の秒は基本的に公表されない。** JMAの`EventID`末尾6桁を秒だと誤読しない
（[2026-08-23 茨城県南部M5.9のログ](log/2026-08-23-ibaraki-nanbu-m5.9-post-hoc-detection.md)で
一度やった誤り）。`--at`/`--eew`には分単位の時刻をそのまま渡し、秒が要る場面
（後述のP波スパイクからの逆算等）は実データ側から推定する。

## 1. 自動検知の有無を確認する

```bash
curl -s "https://api.namazu.dark-kuins.net/events?all=1&size=20" | python3 -m json.tool
```

`all=1`で未評価・人工地震も含めた全件が新しい順に返る。該当時刻付近に`event_id`が
あるかを見る。無ければ`/events`一覧を見るだけで済ませず、**必ず手順2のdetectlab解析まで
やる**（自動検知が無い≠揺れていない。標準設定の閾値未達で正式イベントが立たないことは多い）。

見つかった場合は、その`onset_us`・`max_intensity`・`peak_gal`・`cloud_confirmed`を記録し、
手順2（detectlab裏取り）は任意（自動検知の答え合わせをしたい時だけ）、手順5（手動イベント化）
は不要（すでにイベントがある）。**ただし、保存済み範囲の先にコーダが残っていないかは
必ず確認する**（下記）。

### イベントがあっても、保存済み範囲の先にコーダが残っていないか確認する

自動検知(`cloud_confirmed`)・手動昇格(`manual`)いずれでも、イベントの**保存済み範囲**
（`waveform_prefix`配下。`cloud_confirmed`ならdetectの`POST_SECONDS`、`manual`なら
`promote_event.py`実行時の`--post`までしか波形が残っていない）**の外に、振幅では
目立たないコーダが続いている可能性がある**。2026-08-23の茨城県南部M5.9では、STA/LTAが
閾値を割った後もdevice間の直線性相関が2分近く高いまま残っていた
（[ログ](log/2026-08-23-ibaraki-nanbu-m5.9-post-hoc-detection.md)、区間別の定量化例は
[2026-08-24浦河沖M6.0のログ](log/2026-08-24-urakawa-oki-m6.0-post-hoc-detection.md)参照）。
振幅RMSだけの確認ではこの種のコーダは見えない
（[2026-08-23のバックフィル作業](log/2026-08-23-event-window-backfill.md)で踏んだ限界）。

確認手順:

```bash
# 保存範囲の終端(onset_us + --post、または detect の POST_SECONDS=600秒後)付近を
# 中心に、rawから直接さらに数分先まで見る
python tools/detectlab.py --at "<保存範囲の終端付近>" \
  --eew "<lat>,<lon>,<depth_km>,<発生時刻>" --minutes 5 --device 1 2 \
  --corr-win 2 --out docs/log/img/<slug>-tail-check.png
```

3段目の直線性一致度パネルで、終端に近づくにつれて相関がbackground水準（frac>0.6が
15-25%程度、`2026-08-24`のログの区間別表を参照）まで下がっているかを見る。まだ高いまま
（0.6超が頻発）ならコーダはまだ続いている。

**続いていれば保存範囲を延長する:**

- **`manual`イベント**: `tools/promote_event.py`を**同じ`--onset`のまま`--post`だけ
  伸ばして再実行**する。event_idはonsetの30秒バケットから決まるので同じevent_idを
  指し直し、raw再コピー・`meta.json`再計算・DynamoDBの`manual`レコード更新が冪等に
  上書きされる（何度でも安全に打ち直せる）。
- **`cloud_confirmed`（完全自動）イベント**: `promote_event.py`をそのまま使うと
  `manual`フラグを立てたり、再計算した震度でDynamoDBの確定値を上書きしてしまう
  （detectの計算結果と一致するはずだが、意図せず書き換える必要は無い）。
  [2026-08-23の既存イベントバックフィル](log/2026-08-23-event-window-backfill.md)の
  やり方（`store.copy_raw_to_event`でraw batchを追加コピーし、`meta.json`だけ拡張後の
  全区間で`jma_fft`を再計算して上書き。DynamoDBの`confirmed_intensity`等は触らない）
  に倣う。

延長した/しなかった判断とその根拠は、手順3のログに残す。**どちらの場合も既存event_idの
内容を書き換えているので、手順4末尾のCloudFront invalidationが要る側**（新規発行では
なく既存の書き換え）——`aws cloudfront create-invalidation --paths '/event?id=<eid>'`を
延長した各event_idぶん打つ。

## 2. detectlabで解析する

観測点からの震源距離は`detectlab.py`が`--eew`から自動計算してログに出すので手計算は不要。

### まず標準設定（3軸・1-10Hz）で全体像を1枚

```bash
python tools/detectlab.py --at "<発生時刻、分単位 例 2026-08-23 22:45:00>" \
  --eew "<lat>,<lon>,<depth_km>,<発生時刻>" --minutes 10 --device 1 2 \
  --out docs/log/img/<slug>-8min.png
```

`--minutes 10`は`--at`より後ろを10分見る指定（前側は既定`--lead-min 3`=3分、
`--eew`使用時の背景RMS推定に必要な下限）。P窓/S窓のSNR・直線性が標準出力に出る。
STA/LTA peakが閾値(4)を超えていれば、その時点で「地震らしい」と言い切れる。

**拡大（2分窓ズーム）版は普通は作らない。** 標準設定・低帯域設定の図だけで説明が
つくならそれで十分。人間から「ズームして見せて」と頼まれた時、または閾値ぎりぎりで
視覚的な裏取りがどうしても要る時だけ追加で作る:

```bash
python tools/detectlab.py --at "<P窓付近、分秒>" \
  --eew "<lat>,<lon>,<depth_km>,<発生時刻>" --minutes 2 --lead-min 2 --device 1 2 \
  --out docs/log/img/<slug>-2min-zoom.png
```

### 標準設定で閾値未達・微妙な場合は低帯域・水平2軸も試す

遠地弱震（令和8年熊本地震・2026-08-20茨城県沖M3.5・2026-08-23浦河沖M6.0で有効だった設定）:

```bash
python tools/detectlab.py --at "<発生時刻>" \
  --eew "<lat>,<lon>,<depth_km>,<発生時刻>" --minutes 10 --device 1 2 \
  --band 0.5 2 --axes xy --out docs/log/img/<slug>-lowband-xy.png
```

z軸の低周波ノイズを避けて水平2軸だけを見ることで、遠地の小さい揺れが埋もれにくくなる。
標準設定では閾値未達でも、この設定で両機が閾値を超えることがある
（浦河沖M6.0: 標準3.81/3.83→未達、低帯域5.61/7.67→超過）。

### 判定の目安

`docs/noise.md`「検出できた／できなかった」節に過去事例（震源距離・SNR・直線性と判定の対応）
がある。新しい事例はここに1行追記し、検出限界の参考点を増やしていく。

判定は概ね次の3段階（過去ログの表現に揃える）:
- **probable detection**: 2機が同タイミング・同特徴（直線偏光の上昇、STA/LTAピークの密集）で
  一致。片方だけでも閾値超過があれば強い根拠になる。
- **微妙／要検討**: SNR・直線性がノイズと明確には分離できない。
- **完全埋没**: 標準・低帯域どちらでも背景と区別できない。

### worktreeから実行する時の注意

worktreeには`.venv`が無く`terraform output`も通らないことがある。rawバケット名は
`namazu-data-486414336274`（AWSアカウントIDを含むため変わらない。疑わしければ共有
チェックアウト側の`/Users/nana/codes/NamazuHaUrokoGaNai/terraform`で
`terraform output -raw data_bucket`を引いて照合する）を`--bucket`（または環境変数
`NAMZ_RAW_BUCKET`/`NAMZ_BUCKET`）に直接指定し、`../../../.venv/bin/python3`のように
フルパスでPythonを呼ぶ。

## 3. ログを書く

`docs/log/YYYY-MM-DD-<slug>-post-hoc-detection.md`を新規作成する
（[CLAUDE.mdの規約](../CLAUDE.md)通り、既存ファイルは書き換えない）。書くこと:

- 震源要素・気象庁発表時刻・最大震度（各地の震度一覧があれば要約）
- 自動検知の有無（あれば`event_id`・`onset_us`・確定状態、無ければ`/events?all=1`で確認した旨）
- detectlab解析結果（標準設定の表、必要なら低帯域設定の表、画像）
- 判定（probable detection / 微妙 / 完全埋没）とその根拠
- 新しい知見があれば`docs/noise.md`にも追記し、その旨をログに書く
- `docs/progress.md`に1〜3文の要約+ログへのリンクを1行追記する

## 4. 正式イベントが無ければ手動イベント化する

手順1で該当イベントが無かった場合、raw の保持期限（90日）で消える前に
`tools/promote_event.py`で永久保存する。

```bash
export NAMZ_BUCKET=namazu-data-486414336274   # rawバケット名。変わらないので固定値でよい
export NAMZ_EVENTS_TABLE=namazu-events
export AWS_REGION=ap-northeast-1
python tools/promote_event.py --onset "<発生時刻 or 検知した立ち上がり時刻>" \
  --pre 180 --post 600 --device 1 --note "<地震の要約。詳細ログへのパスも書く>" --dry-run
```

`--dry-run`で内容（event_id・バッチ数・計測震度）を確認してから`--yes`を付けて実行する。
onsetは検知できていれば実際の立ち上がり時刻、判然としなければ発生時刻そのものでよい。
**`--post`は迷ったら300〜600秒まで広げる**（振幅では目立たないコーダが後続することがある。
`docs/log/2026-08-23-event-post-window-extension.md`参照）。デバイスごとに繰り返し、

```bash
python tools/flag_event.py relate 0001-<bucket> 0002-<bucket>
```

で相互リンクする。

**CloudFront invalidationは、書き換え時点でそのevent_idが既に一般に取得され得た場合だけ要る。**
`/event`のキャッシュキーは`id`クエリを含みevent_idごとに別エントリなので、判断基準は
「新規か既存か」ではなく「その時点までに誰かが`/event?id=<eid>`を叩けた（＝キャッシュされ得た）
か」。具体的には:

- **今回のように`promote_event.py`で新規発行した直後に`relate`/`note`で続けて書き換える一連の
  操作は不要。** event_idは昇格するまで存在せず、ダッシュボードのどこにもリンクされていない
  ため、昇格からrelateまでの間に誰かが取得できる余地が実質無い。relateが「書き換え」である
  ことは事実だが、その前の状態を誰もキャッシュしていないので、初回フェッチはrelate後の
  最新内容をそのまま返す。
- **要るのは、その時点で既に一覧・ダッシュボード等から辿れる状態だった（＝取得され得た）
  event_idを後から書き換える時。** 手順1のコーダ延長（自動検知・前セッションでの手動昇格など、
  既に存在していたevent_idに対して`relate`後にさらに`note`を足す等）はここに該当する。

打つ時は`--paths`に実際に書き換えたevent_idを`/event?id=<eid>`の形で列挙する。
**`/event*`のようなワイルドカードは使わない**——キャッシュキーがevent_idごとに
分かれているので、絞らずに全消しすると触っていない確定済みイベント(実質1年キャッシュ)
まで巻き添えで飛ばし、長期キャッシュを入れた目的（閲覧人数比例のS3 GET対策）を
自分で壊すことになる（[#141](https://github.com/nna774/NamazuHaUrokoGaNai/pull/141)、
`tools/README.md`参照）。

```bash
aws cloudfront create-invalidation \
  --distribution-id "$(cd ../../../terraform && terraform output -raw api_distribution_id)" \
  --paths '/event?id=0001-<bucket>' '/event?id=0002-<bucket>'
```
