# 生涯最小空きヒープ機能(PR #183)をmerge・本番デプロイした

PR #183（`ESP.getMinFreeHeap()`のテレメトリ化）をmergeし、Lambda(`api`/`detect`/
`ingest`/`watchdog`の4本)とダッシュボードを本番反映した。

- `terraform/build_lambda.sh`でzip再ビルド→`terraform apply`（差分はLambdaコードの
  `source_code_hash`更新のみ、4 changed/0 added/0 destroyed）
- `dashboard/app.js`をS3 sync（差分は`app.js`のみ）、CloudFront invalidation
  （`dashboard_distribution_id`に対し`/app.js`・`/index.html`の2パスのみ。
  `api`側distributionやワイルドカードには触れていない）

master時点でPR #183以外にも未デプロイのLambda変更（coredump自動送信のPR #167/#171等）が
積まれていたため、今回のデプロイはそれらも合わせて本番に反映される形になった。この
リポジトリはPR単位の個別デプロイではなく都度ビルド全体をデプロイする運用のため、想定通り。

**実機ファームのOTA配信・実機での`X-Namz-Heap-Minfree`到達確認はまだ**
（[docs/progress.md](../progress.md)の該当行に既に記載済みの通り）。今回やったのは
サーバ側の受け入れ準備であり、ファームが実際にヘッダを送るには別途OTA配信が必要。
