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

## 注意

- `lifecycle` は prefix 単位でしか expiration できないため、「イベント周辺だけ永久保存」は
  detect が `events/` へ**コピー**して実現している（raw/ は消えても events/ は残る）。
- Function URL は認証NONE。バッチ/アラートはアプリ層のHMACで守り、apiは読み取り専用で公開。
- numpy は `build_lambda.sh` が manylinux ホイールで同梱する。scipyは不要（FFT版のみ使用）。
