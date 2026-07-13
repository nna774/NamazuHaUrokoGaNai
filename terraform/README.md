# terraform — AWSリソース

S3(raw 90日/events 永久)・DynamoDB・Lambda×3(Function URL)・S3→detect通知・
CloudFrontダッシュボード・IAM。

## 構成

| ファイル | 内容 |
|----------|------|
| `s3.tf` | データバケット。raw/ は lifecycle で90日expire、events/ は対象外で永久。raw/作成で detect起動 |
| `dynamodb.tf` | イベントテーブル（PAY_PER_REQUEST） |
| `lambda.tf` | ingest/detect/api。ingest・api に Function URL(認証NONE) |
| `iam.tf` | Lambda実行ロール（S3/DynamoDB/logs） |
| `dashboard.tf` | 非公開S3 + CloudFront(OAC)。認証なし配信 |

## デプロイ

```bash
cp terraform.tfvars.example terraform.tfvars   # 値を埋める
./build_lambda.sh                              # Lambda zip を builds/ に生成（applyの前に必須）
terraform init
terraform apply
```

出力される `ingest_url` を firmware の `secrets.h`（kIngestUrl、kAlertUrl=…/alert）へ、
`api_url` を dashboard の設定へ、`dashboard_url` がブラウザで開くURL。

## カスタムドメイン(namazu.dark-kuins.net / api.namazu.dark-kuins.net)

DNSは外部(Cloudflare, `nna774/dark-kuins.net-dns`。手元では `../dark-kuins.net-dns`)管理。
ACMのDNS検証と本番CNAMEは向こうのリポジトリに手で足すため、リポジトリまたぎの順序がある
(`custom_domain.tf`参照)。

```bash
# 1. まず証明書だけ作る
terraform apply -target=aws_acm_certificate.custom
terraform output acm_validation_records      # 検証用CNAME(name→value)

# 2. nna774/dark-kuins.net-dns の records.yml(dark-kuins.net > acm:)へ転記して apply
#    name の末尾 .dark-kuins.net. を落としたものがキー。例:
#      _abc123.namazu:      _xyz.acm-validations.aws
#      _def456.api.namazu:  _uvw.acm-validations.aws

# 3. 検証完了を待って本体を apply(CloudFrontにalias付与)
terraform apply
terraform output dashboard_cname_target       # namazu の向き先(dxxxx.cloudfront.net)
terraform output api_cname_target             # api.namazu の向き先

# 4. records.yml(dark-kuins.net > cname:)へ転記して apply(proxied=false=grey固定)
#      namazu:      dxxxx.cloudfront.net
#      api.namazu:  dyyyy.cloudfront.net

# 5. dashboard/config.js の NAMZ_API_URL を https://api.namazu.dark-kuins.net にして再デプロイ
```

`dashboard_domain` / `api_domain` を空にすると従来どおり CloudFront 既定ドメイン+
Function URL のまま(両方セット時のみ有効)。api.namazu は2階層深いので Cloudflare は
必ず grey(proxied=false)にする(Universal SSL の対象外で、TLSはAWS側ACMで終端する)。

## 注意

- `lifecycle` は prefix 単位でしか expiration できないため、「イベント周辺だけ永久保存」は
  detect が `events/` へ**コピー**して実現している（raw/ は消えても events/ は残る）。
- Function URL は認証NONE。バッチ/アラートはアプリ層のHMACで守り、apiは読み取り専用で公開。
- numpy は `build_lambda.sh` が manylinux ホイールで同梱する。scipyは不要（FFT版のみ使用）。
