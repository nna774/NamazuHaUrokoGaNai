# CloudFrontのエッジキャッシュとブラウザキャッシュを別レイヤーで制御する

## 何を決めたか

`terraform/dashboard.tf`のCloudFront distributionを2点変更した。

1. `default_cache_behavior`をlegacy `forwarded_values`から
   `cache_policy_id = Managed-CachingOptimized`へ切り替えた。
2. `aws_cloudfront_response_headers_policy`を新設し、ビューワー(ブラウザ)への
   応答へ`Cache-Control: no-cache`を強制的に付与するようにした
   （`response_headers_policy_id`で`default_cache_behavior`に紐付け）。
3. S3オブジェクト自体には`Cache-Control`を一切付けないようにした
   （デプロイ手順から`--cache-control 'no-cache'`を削除。
   CLAUDE.md・dashboard/README.md・docs/STATUS.md）。

## なぜそう決めたか

前回のPR（[2026-08-06-device-status-fw-version-header.md](2026-08-06-device-status-fw-version-header.md)）で、
ブラウザが`app.js`だけ古いキャッシュを使い続ける不具合を踏み、対策として
S3オブジェクトへ`Cache-Control: no-cache`を付ける方針にした。

ユーザーから「デプロイのたびにCloudFrontをinvalidationしているのだから、
毎回S3へ再検証しに行く必要はないのでは」と指摘され、確認したところ
その通りだった。`curl -I`で実測すると、`no-cache`を送っている間は
`x-cache: RefreshHit from cloudfront`が毎回返り、エッジがS3へ再検証しに
行っていることが分かった。

最初に試したのが`cache_policy_id`をlegacy `forwarded_values`から
`Managed-CachingOptimized`(DefaultTTL=1日)へ切り替える案。適用したが
効果がなかった——**CloudFrontはCache PolicyのDefaultTTLより、オリジンが
明示した鮮度ヘッダー(Cache-Control/Expires)を優先する**ため、S3が
`no-cache`を返し続ける限り、Cache Policyを変えてもエッジのTTLは
実質ゼロ近く（`MinTTL`が0→1になっただけ）のままだった。

根本原因は「ブラウザ向けの指示」と「CloudFrontエッジのキャッシュ判断」を
**同じ1本のヘッダーで兼用しようとしていたこと**。この2つは本来別のレイヤーで、
分離するには「エッジのキャッシュ可否判断が終わった後に、ビューワーへの応答へ
ヘッダーを足す」仕組みが要る。CloudFrontの`Response Headers Policy`はまさに
それで、キャッシュ判断（オリジンの生ヘッダー基準）とは独立して動く。

## 何が覆ったか

- 「S3オブジェクトに`Cache-Control: no-cache`を付ける」という前PRの対策 →
  **CloudFront Response Headers Policyで付与する方式に置き換えた**。
  S3側に付けたままだとCache Policyを変えても効果が出ないと実測で分かったため。
- 当初「`cache_policy_id`をCachingOptimizedに変えれば十分」と考えていたが、
  実測（`x-cache`ヘッダーの推移）で不十分と判明し、Response Headers Policyの
  追加が必要だと分かった。

## 次に何が可能になったか

- `curl -I`で確認: 2回目以降のリクエストが`x-cache: Hit from cloudfront`
  （エッジ完結、S3への再検証なし）になり、`Cache-Control: no-cache`は
  引き続きビューワーへ届く。デプロイのたびのinvalidationで鮮度は保証されたまま、
  通常時のエッジ↔S3間の無駄な再検証が無くなった。
- ブラウザ側は相変わらず毎回CloudFrontへ再検証しにいく（軽い、304で済む）ので、
  前PRで踏んだ「app.jsだけ古いキャッシュが残る」不具合は再発しない。
