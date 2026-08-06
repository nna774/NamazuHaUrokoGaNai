# ダッシュボード配信: 非公開S3 + CloudFront(OAC)。認証なしで誰でも閲覧可。
resource "aws_s3_bucket" "dashboard" {
  bucket = local.dash_bucket
  # 静的ファイルだけなので destroy 時に中身ごと消せるようにする（作り直しが多い）。
  # データ用バケット(s3.tf)には付けない: 地震データを誤って一括削除しないため。
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "dashboard" {
  name                              = "${local.name}-dashboard"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ビューワー(ブラウザ)へは常に Cache-Control: no-cache を付ける。ブラウザに
# 「使う前に毎回再検証しろ」と伝える指示で、CloudFrontのエッジキャッシュTTLとは
# 別レイヤー。エッジ↔S3間の再検証は cache_policy_id 側（CachingOptimizedの
# DefaultTTL）に任せ、ここではビューワー向けの応答ヘッダーだけを差し替える。
#
# 試した順序と教訓: 当初S3オブジェクト自体にCache-Control: no-cacheを付けたが、
# CloudFrontはCache PolicyのDefaultTTLより「オリジンが明示した鮮度ヘッダー」を
# 優先するため、CachingOptimized(DefaultTTL=1日)に切り替えてもオリジンの
# no-cacheがそのまま効いてしまい、エッジ↔S3間の再検証が毎回発生し続けていた
# （実測: MinTTLが0→1に上がっただけで実質変化なし）。Response Headers Policyは
# キャッシュ判断が終わった後にビューワーへの応答へヘッダーを足す仕組みなので、
# エッジのキャッシュ可否には影響しない——これで初めて「エッジは長くキャッシュ・
# ブラウザは毎回再検証」の分離が成立する。
resource "aws_cloudfront_response_headers_policy" "dashboard_no_cache" {
  name = "${local.name}-dashboard-no-cache"
  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = "no-cache"
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "dashboard" {
  enabled             = true
  default_root_object = "index.html"
  aliases             = local.custom_domain_enabled ? [var.dashboard_domain] : []

  origin {
    domain_name              = aws_s3_bucket.dashboard.bucket_regional_domain_name
    origin_id                = "dashboard"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard.id
  }

  default_cache_behavior {
    target_origin_id       = "dashboard"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    # Managed-CachingOptimized: エッジのTTL(既定1日)はここで管理する。デプロイの
    # たびにinvalidationしているので、通常時のビューワーリクエストではエッジ↔S3間の
    # 再検証は起きない。
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.dashboard_no_cache.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # カスタムドメインありなら ACM(us-east-1)、なければ CloudFront 既定証明書。
  dynamic "viewer_certificate" {
    for_each = local.custom_domain_enabled ? [1] : []
    content {
      acm_certificate_arn      = local.cert_arn
      ssl_support_method       = "sni-only"
      minimum_protocol_version = "TLSv1.2_2021"
    }
  }
  dynamic "viewer_certificate" {
    for_each = local.custom_domain_enabled ? [] : [1]
    content {
      cloudfront_default_certificate = true
    }
  }

  price_class = "PriceClass_200"
}

data "aws_iam_policy_document" "dashboard_bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.dashboard.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.dashboard.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  policy = data.aws_iam_policy_document.dashboard_bucket.json
}
