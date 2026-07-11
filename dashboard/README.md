# dashboard — 波形・イベント可視化

外部依存なしの単一ページ（vanilla JS + Canvas）。ビルド不要。

## 機能

- **ライブ**: 直近 n分（1/3/5/10/60）の波形。範囲が広いと min/max エンベロープ表示。自動更新
- **イベント**: 検知イベント一覧（震度・計測震度・ピーク・速報/確定フラグ）。クリックで周辺波形

## API URL の指定

優先度: `?api=<url>` クエリ > 画面の入力欄(localStorage) > `config.js` の `window.NAMZ_API_URL`。

## デプロイ

```bash
cp config.example.js config.js   # terraform output の api_url を記入
BUCKET=$(cd ../terraform && terraform output -raw dashboard_bucket)
aws s3 sync . "s3://$BUCKET/" --exclude 'config.example.js' --exclude 'README.md'
```

`terraform output dashboard_url` の CloudFront URL で開く。

## ローカル確認

```bash
python3 -m http.server 8080   # http://localhost:8080 （?api=... でAPIを指定）
```
