# dashboard — 波形・イベント可視化

外部依存なしの単一ページ（vanilla JS + Canvas）。ビルド不要。

## 機能

- **ライブ**: 直近 n分（1/3/5/10/60）の波形。範囲が広いと min/max エンベロープ表示。自動更新
- **イベント**: 検知イベント一覧（機・震度・計測震度・ピーク・速報/確定フラグ）。クリックで周辺波形。
  「機」セレクタでデバイス絞り込み（既定は全機。絞り込みは `#events?d=<id>` としてURLに載る）
- **デバイス**: 各デバイスの生存状態（オンライン/欠測・最終受信・データ鮮度・累計バッチ・
  版数・再起動要求・OTA適用状況）。`/devices` を定期取得。欠測の能動通知は watchdog Lambda が
  Slack に飛ばす

## API URL の指定

優先度: `?api=<url>` クエリ > 画面の入力欄(localStorage) > `config.js` の `window.NAMZ_API_URL`。

## デプロイ

```bash
cp config.example.js config.js   # terraform output の api_url を記入
BUCKET=$(cd ../terraform && terraform output -raw dashboard_bucket)
aws s3 sync . "s3://$BUCKET/" --exclude 'config.example.js' --exclude 'README.md' \
  --cache-control 'no-cache'
```

`terraform output dashboard_url` の CloudFront URL で開く。**`--cache-control 'no-cache'`
を忘れると**、Cache-Controlの乗らないオブジェクトをブラウザがヒューリスティックキャッシュで
長く抱え込みうる。CloudFrontのinvalidationはCDNエッジのキャッシュしか消せずブラウザには
効かないので、`index.html`だけ新しく`app.js`は古いまま、という食い違いが起きうる
（実際に踏んだ、2026-08-06）。

## ローカル確認

```bash
python3 -m http.server 8080   # http://localhost:8080 （?api=... でAPIを指定）
```
