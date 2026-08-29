# データ用バケット: raw/（60日でexpire、削除後さらに30日分は復旧可能）と events/（永久）と
# coredump/（60日でexpire。秘密情報が写り込んでいる可能性があるため events/ のように
# 永久保持にはしない。docs/log/2026-08-29-coredump-auto-upload-plan.md）
resource "aws_s3_bucket" "data" {
  bucket = local.data_bucket
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# events/ の誤delete・誤上書きから復元できるようにバージョニングを有効化する。
# バージョニング下では expiration は current version に delete marker を乗せる
# だけで、実体（旧 current version）は noncurrent_version_expiration の日数が
# 経つまで物理的に残り続ける（課金もされるが、その間は復旧可能）。下の
# expire-raw ルールの noncurrent_days=30 はこれを利用していて、万一そのルールの
# filter prefix が誤って広がり events/ を巻き込んでも（Denyポリシーが効かない
# 既知の穴。下のコメント参照）、実体が消えるまで最大30日の発見・復旧猶予がある。
# raw/ 自身にとっては「消える予定だったデータを30日長く残す」だけなので、
# アプリから見える寿命(raw_retention_days)には影響しない。
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # raw/ 配下だけを保持期間で削除。events/ は対象外なので永久に残る。
  #
  # 【重要】このfilter prefixを広げたりtypoしたりして誤って events/ を含めると、
  # 下の aws_s3_bucket_policy.data の Deny は一切効かず黙って消える。Lifecycle
  # expirationはS3サービス内部の自動処理であり、特定のIAMプリンシパルによる
  # リクエストとして発行されるわけではないため、バケットポリシー/IAMポリシーの
  # 評価対象外（AWSの既知の挙動）。ここを触る時は "raw/" のままであることを
  # 必ず確認すること。
  rule {
    id     = "expire-raw"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    expiration {
      days = var.raw_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  # coredump/ 配下も同様に保持期間で削除する。秘密情報(WiFiパス・HMAC鍵)が写り込んで
  # いる可能性がある前提で扱う(docs/log/2026-08-29-coredump-auto-upload-design-discussion.md)
  # ため、events/ のような永久保持にはせず露出期間を絞る。raw/ と違い変数化はせず固定60日。
  rule {
    id     = "expire-coredump"
    status = "Enabled"
    filter {
      prefix = "coredump/"
    }
    expiration {
      days = 60
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# events/ への削除系操作を明示的に拒否する。IAM側の許可（誰が消せるか）とは別に、
# S3の評価ではDenyが最優先されるため、これがある限りaws CLIの誤操作やコンソールからの
# 直接削除も止まる。本当に消したい時はこのDeny文を一旦外してからでないと通らない。
data "aws_iam_policy_document" "data_bucket_protect_events" {
  statement {
    sid    = "DenyDeleteEvents"
    effect = "Deny"
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.data.arn}/events/*",
    ]
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id
  policy = data.aws_iam_policy_document.data_bucket_protect_events.json
}

# raw/ にオブジェクトが作られたら detect Lambda を起動
resource "aws_s3_bucket_notification" "raw_created" {
  bucket = aws_s3_bucket.data.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.detect.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
  }

  depends_on = [aws_lambda_permission.detect_from_s3]
}
