# カスタムドメイン: namazu.dark-kuins.net(ダッシュボード) / api.namazu.dark-kuins.net(API)。
# DNSは外部(Cloudflare, nna774/dark-kuins.net-dns)管理なので、
# ACMのDNS検証レコードと本番CNAMEは向こうのリポジトリで手で足す。ここでは AWS 側のリソースだけ作る。
#
# apply 順序(リポジトリまたぎの鶏卵に注意):
#   1. terraform apply -target=aws_acm_certificate.custom
#   2. 出力 acm_validation_records を nna774/dark-kuins.net-dns の records.yml(acm:) に転記して apply
#   3. terraform apply   (検証完了→CloudFrontにalias付与まで通る)
#   4. 出力 dashboard_cname_target / api_cname_target を records.yml(cname:) に転記して apply
#   5. dashboard/config.js を https://api.namazu.dark-kuins.net に差し替えて再デプロイ

locals {
  # 両方セットされている時だけカスタムドメインを有効化する(片方だけは非対応)。
  custom_domain_enabled = var.dashboard_domain != "" && var.api_domain != ""
  # 検証完了後の証明書ARN。distribution はこれを参照して検証完了まで待つ。
  cert_arn = local.custom_domain_enabled ? aws_acm_certificate_validation.custom[0].certificate_arn : null
}

# CloudFront 用証明書は us-east-1 必須。SAN 1枚で両ドメインをまかなう。
resource "aws_acm_certificate" "custom" {
  count                     = local.custom_domain_enabled ? 1 : 0
  provider                  = aws.us_east_1
  domain_name               = var.dashboard_domain
  subject_alternative_names = [var.api_domain]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# DNS が外部なので検証レコードは TF では作らない。Cloudflare に手で入れた後、
# ACM が ISSUED になるのをここで待つ(validation_record_fqdns は敢えて省略)。
resource "aws_acm_certificate_validation" "custom" {
  count           = local.custom_domain_enabled ? 1 : 0
  provider        = aws.us_east_1
  certificate_arn = aws_acm_certificate.custom[0].arn
}

# /recent: 認証なし公開のため閲覧人数がそのままS3 GET回数に比例していた
# (Electabuzz PR#29 https://github.com/nna774/Electabuzz/pull/29 と同じ構造の問題)。
# 新データはバッチ送信間隔(最速のdevice2で15秒、firmware/src/config.hのkBatchSeconds)より
# 速くは来ないので、固定15秒TTLでキャッシュしても鮮度は落ちない。minutes/start/deviceの
# 組ごとに別キーなので、同じ窓を何人見ていてもオリジン(Lambda→S3)へのアクセスは一定になる。
resource "aws_cloudfront_cache_policy" "api_recent" {
  count       = local.custom_domain_enabled ? 1 : 0
  name        = "namazu-api-recent"
  min_ttl     = 0
  default_ttl = 15
  max_ttl     = 15

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "whitelist"
      query_strings {
        items = ["minutes", "start", "device"]
      }
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

# /event: クラウド確定済み(meta.jsonあり)の波形は書き込み後不変なので実質半永久(1年)まで
# キャッシュできる。一方、速報のみ(meta.json未生成)の間にキャッシュしてしまうと、直後に
# クラウド確定してもTTL分は「波形なし」を返し続けてしまう——地震直後に見に来た人ほど
# これを踏みやすい。そのためTTLは固定値ではなくLambda側がCache-Controlヘッダで出し分ける
# (速報のみ=max-age=0で実質無効化、確定後=EVENT_CONFIRMED_CACHE_S=1年。lambda/api/handler.py参照)。
# note/checked等の手動編集(flag_event.py)をすぐ反映させたい時は自然失効を待たず
# `aws cloudfront create-invalidation --paths '/event*'` を打つ。
# ここのdefault_ttl=0は「オリジンがヘッダを返さなかった場合」の保険で、通常は使われない。
resource "aws_cloudfront_cache_policy" "api_event" {
  count       = local.custom_domain_enabled ? 1 : 0
  name        = "namazu-api-event"
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 31536000 # 365日。EVENT_CONFIRMED_CACHE_S(lambda/api/handler.py)と揃える

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "whitelist"
      query_strings {
        items = ["id", "from", "to"]
      }
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

# API(Lambda Function URL)はカスタムドメインを直接張れないので CloudFront で前段する。
# ライブデータの陳腐化を避けるため既定はキャッシュ無効(CachingDisabled)。
# /recent・/event だけは上記の専用cache policyで個別にキャッシュを効かせる。
resource "aws_cloudfront_distribution" "api" {
  count   = local.custom_domain_enabled ? 1 : 0
  enabled = true
  aliases = [var.api_domain]

  origin {
    # Function URL のホスト部。Host ヘッダは転送しない(下の origin request policy)。
    domain_name = "${aws_lambda_function_url.api.url_id}.lambda-url.${var.region}.on.aws"
    origin_id   = "api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    # Managed-CachingDisabled: ライブAPIをキャッシュしない。
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    # Managed-AllViewerExceptHostHeader: Host以外を素通し。
    # Function URL は自分のホスト名を要求するので Host は転送しない。CORS用にOriginは通す。
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  # path_pattern はワイルドカード無しなのでパス完全一致(/eventは/eventsに巻き込まれない)。
  ordered_cache_behavior {
    path_pattern             = "/recent"
    target_origin_id         = "api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.api_recent[0].id
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  ordered_cache_behavior {
    path_pattern             = "/event"
    target_origin_id         = "api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.api_event[0].id
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = local.cert_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  price_class = "PriceClass_200"
}
