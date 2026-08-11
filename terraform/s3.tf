# データ用バケット: raw/（90日でexpire）と events/（永久）
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
# raw/ は versioning が無かった前提で「90日で本当に消える」設計なので、有効化した
# ままだと expiration が current version を消すだけで旧バージョンが非current化して
# 課金上は残り続けてしまう（意図した「消える」が壊れる）。下の lifecycle 側で
# noncurrent_version_expiration を足して raw/ の旧バージョンも即座に消し、実質的に
# バージョニング無しだった頃と同じ「90日で本当に消える」挙動を保つ。
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # raw/ 配下だけを保持期間で削除。events/ は対象外なので永久に残る。
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
      noncurrent_days = 1
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
