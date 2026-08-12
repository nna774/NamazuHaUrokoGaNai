# dashboard — 波形・イベント可視化

外部依存なしの単一ページ（vanilla JS + Canvas）。ビルド不要。

## 機能

- **ライブ**: 直近 n分（1/3/5/10/30）の波形。範囲が広いと min/max エンベロープ表示。自動更新。
  「1分」表示時は取得済みの生波形からブラウザ内で**概算震度**を計算して表示する
  （気象庁計測震度のFIR近似・追加のサーバ通信なし。詳細は下記）。同じく「1分」表示限定で、
  較正済みの機を2台以上選ぶと**重ね表示**に切り替わる（詳細は下記）
- **イベント**: 検知イベント一覧（機・震度・計測震度・ピーク・速報/確定フラグ）。クリックで周辺波形。
  「機」セレクタでデバイス絞り込み（既定は全機。絞り込みは `#events?d=<id>` としてURLに載る）
- **デバイス**: 各デバイスの生存状態（オンライン/欠測・最終受信・データ鮮度・累計バッチ・
  版数・再起動要求・OTA適用状況）。`/devices` を定期取得。欠測の能動通知は watchdog Lambda が
  Slack に飛ばす。行クリックで個別ページ(`#device/<id>`)へ。センサ内蔵温度のトレンド
  チャートを持つ（`/devices/<id>/temp`。温度計を持たない機体はデータなし表示）

## クライアント側の概算震度（ライブ・1分表示）

API の `/recent` は `MAX_POINTS`(=6000=1分@100Hz) 以下ならrawで返す。ライブ画面の既定窓
（1分）はちょうどこの範囲に収まるので、**ガル波形を描くために既に取得済みのデータだけ**
から震度も計算できる（追加のAPI呼び出しは無い）。3分以上の窓や拡大表示はenvelope
（min/max間引き）になり生サンプルを失うため、震度は計算しない。

計算は `tools/jismo/realtime.py`（オフライン一括版）と同じ手順を `app.js` に移植したもの:
FIR係数（`tools/jismo/fir.py --fs 100 --numtaps 511` で設計。`firmware/lib/Shindo/JmaFirTaps.h`
と同一の値）で3軸を畳み込み→ベクトル合成→ゼロ初期履歴による整定時間(numtaps+1秒ぶん)を
捨てる→超過時間0.3秒のa0→気象庁の丸め。fs・numtapsを変えたら埋め込み配列
（`app.js` の `JMA_FIR_TAPS`）も再生成すること。

イベント一覧・詳細の確定震度は `tools/jismo/` そのもの（FFT版、サーバ側）が真実。
ライブの概算値は同じフィルタの近似移植かつ移動窓の切り方も違うため、**あくまで参考値**
であり確定値とは僅かにずれ得る（表示にも明記している）。

## 重ね表示（ライブ・1分限定）

`tools/calibrate_orientation.py --write` で傾き・相対方位を較正済み（`namazu-devices` に
`tilt_up`/`azimuth_deg` 書き込み済み）の機を「重ね表示」で2台以上チェックすると、通常の
x/y/z波形の代わりに複数機を重ねて描く（[docs/device_overlay.md](../docs/device_overlay.md)
§3.bの実装）。「1分」表示限定（生波形が要るため。概算震度と同じ制約）で、ドラッグ拡大は
非対応。URLは `#live?m=1&overlay=<id>,<id>,...` の形で状態を持つ。

- **描くもの**: UD（鉛直、実線）と、較正値で回転して基準機の水平基底へ揃えたh1/h2
  （回転後の水平2軸、破線/点線）。機ごとに色分けする。窓内平均を重力DC近似として引く
  （通常のドローと同じ近似）。
- **回転**: `tilt_up`（raw sensor frameでの重力方向の単位ベクトル）から作った基底へ射影し、
  `azimuth_deg`（`calibration_ref_device`の水平基底へ揃える回転角）ぶん水平2軸を回す。
  相対方位はまだ真北ではなく基準機からの相対値（[docs/device_overlay.md](../docs/device_overlay.md)
  参照）。
- **共通グリッド**: サンプルクロックは機ごとに独立なので、代表機（選択中で最若番のid）の
  サンプル間隔・実測範囲の共通部分へ他機を線形補間してから重ねる。
- **計測震度バッジ**: 重ね表示中は機ごとに表示する。震度算出は回転・符号反転に不変
  （[docs/design.md](../docs/design.md)「向きは自由」）なので、較正の有無によらず生の
  x/y/zからそのまま計算する。
- 選んだ機の`calibration_ref_device`が食い違う組み合わせ、較正値が無い機を含む組み合わせは
  エラー表示にする（重ねられないため）。

## URLハッシュルーティング

画面状態（タブ・表示範囲・自動更新・軸表示・ページ等）は `location.hash` に持たせている
（`app.js` の `parseHash`/`route`、実装は同ファイル1429行目以降）。リロード・共有URLで
状態が復元される。ハッシュはSPA内部の状態表現であり、サーバ側に対応するエンドポイントは
無い（`curl`や`fetch`でこのURLを直接取っても、返るのは静的な`index.html`だけで
`#`以降のJS側の状態は反映されない。中身を見るにはブラウザでJSを実行させる必要がある）。

- `#live?m=<分>&auto=<0|1>&r=<レンジ>&ax=<軸文字列>&s=<epoch秒>&t=<fromUs>-<toUs>&d=<device_id>&overlay=<id>,<id>,...`
  ライブタブ。`m`は表示分数(1/3/5/10/30)、`auto`は自動更新、`r`は縦軸レンジ。
  `ax`は表示中の軸を連結した文字列（例 `xy`=z非表示、``=全非表示、省略=全表示=`xyz`と同じ扱い）。
  `s`を指定すると「今」ではなくその時刻を起点に表示（ドラッグ拡大等で付く）。
  `t`はドラッグ拡大した固定の時間窓（マイクロ秒epoch、`fromUs-toUs`）。
  `d`は単一機表示時のデバイス絞り込み。`overlay`は較正済み機の重ね表示
  （2台以上、詳細は下記「重ね表示」節）。
- `#events?p=<頁>&all=<0|1>&d=<device_id>`
  イベント一覧タブ。`p`はページ番号、`all`はartificial/未確定も含めるフィルタ、
  `d`はデバイス絞り込み（既定`all`は省略）。
- `#event/<id>?p=&all=&d=&r=&ax=&t=<fromUs>-<toUs>`
  イベント詳細。`p`/`all`/`d`は戻り先の一覧状態、`r`/`ax`/`t`は詳細波形の縦軸レンジ・
  軸表示・時間ズーム。
- `#devices`
  デバイス一覧タブ。
- `#device/<id>?h=<時間>`
  デバイス詳細。`h`は温度トレンドの表示期間（時間）。

ハッシュが上記どれにもマッチしない場合（空文字含む）は既定でライブタブになる（`route()`の
`else`節）。

### エージェントがURLの中身を確認する時はAPIを直接叩け

**このURLをChromeで開いて中身を確認しようとするな。** 波形は`<canvas>`描画でDOM/テキストに
出ないため、DOM読み取りでは何も取れずスクリーンショット頼みになり不確実・低速。ハッシュの
パラメータは下表でAPIのクエリに機械的に変換できるので、そのAPIを`curl`/`fetch`で直接叩いて
JSONを見る方が確実で速い（APIは認証なし・読み取り専用。ベースURLは`config.js`の
`window.NAMZ_API_URL`、本番は`https://api.namazu.dark-kuins.net`）。

| ハッシュ | 対応するAPI呼び出し |
|---|---|
| `#live?m=<m>&d=<device>&s=<sec>` | `GET /recent?minutes=<m>&device=<device>` （`s`があれば`&start=<sec*1e6>`） |
| `#live?...&t=<fromUs>-<toUs>`（ドラッグ拡大） | `GET /recent?minutes=<max(0.1,(toUs-fromUs)/60e6)>&start=<fromUs>&device=<device>` |
| `#events?p=<p>&all=<all>&d=<device>` | `GET /events?page=<p-1>&size=20&all=<all>&device=<device>` |
| `#event/<id>?...` | `GET /event?id=<id>` |
| `#devices` | `GET /devices` |
| `#device/<id>?h=<h>` | `GET /devices/<id>` （温度トレンドは`GET /devices/<id>/temp?hours=<h>`） |

`d`/`device`はデバイス絞り込み無し（`all`扱い）なら省略。`m`や`d`等の元パラメータの意味は
上のハッシュ一覧を参照。

**`/recent`はMAX_POINTS(=6000点、100Hzで1分)を超える窓ではenvelope（min/max間引き）
にした値しか返さない。** `m=5`のような数分の窓は既にenvelopeで、生サンプルではない。
詳細な波形解析や複数分/長時間ぶんの生波形が要る時は、`/recent`を叩くのではなくS3の`raw/`
を直接読め。既存の`tools/detectlab.py --at "<時刻>" --minutes <分> [--device <id>...]`
（または`--event <id>`）がまさにこれをやる（フルレートの生波形を取得してSTA/LTA・
スペクトログラム等の解析まで一気にやる。用途に合わなければ`--dump-csv`で生窓だけCSV保存
できる）。自前で組む場合は`lambda/common/store.py`の`load_window`/`list_raw_keys_in_range`
（**device_id必須**。理由は`CLAUDE.md`の「波形を組み立てる時は必ずdevice_idで絞る」参照）。

## API URL の指定

優先度: `?api=<url>` クエリ > 画面の入力欄(localStorage) > `config.js` の `window.NAMZ_API_URL`。

## デプロイ

```bash
cp config.example.js config.js   # terraform output の api_url を記入
BUCKET=$(cd ../terraform && terraform output -raw dashboard_bucket)
aws s3 sync . "s3://$BUCKET/" --exclude 'config.example.js' --exclude 'README.md'
```

`terraform output dashboard_url` の CloudFront URL で開く。**S3オブジェクトに
`--cache-control` は付けない**（意図的）。ブラウザ向けの`Cache-Control: no-cache`は
CloudFront側の`aws_cloudfront_response_headers_policy`が付与し、エッジのキャッシュ
TTLとは別レイヤーで制御している（`terraform/dashboard.tf`参照）。S3側に付けると
CloudFrontのエッジ↔S3間の再検証まで毎回発生してしまうので、混ぜるな
（実際に踏んだ、2026-08-06）。

## ローカル確認

```bash
python3 -m http.server 8080   # http://localhost:8080 （?api=... でAPIを指定）
```
