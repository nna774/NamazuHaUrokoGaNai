# dashboard — 波形・イベント可視化

外部依存なしの単一ページ（vanilla JS + Canvas）。ビルド不要。

## 機能

- **ライブ**: 直近 n分（1/3/5/10/30）の波形。範囲が広いと min/max エンベロープ表示。自動更新。
  「1分」表示時は取得済みの生波形からブラウザ内で**概算震度**を計算して表示する
  （気象庁計測震度のFIR近似・追加のサーバ通信なし。詳細は下記）
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
