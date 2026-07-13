output "ingest_url" {
  description = "firmware secrets.h の kIngestUrl。/alert を付けたものが kAlertUrl。"
  value       = aws_lambda_function_url.ingest.function_url
}

output "api_url" {
  description = "読み取りAPIのURL。カスタムドメインありならそちら、なければFunction URL。"
  value       = local.custom_domain_enabled ? "https://${var.api_domain}" : aws_lambda_function_url.api.function_url
}

output "dashboard_url" {
  description = "ダッシュボードの公開URL。"
  value       = local.custom_domain_enabled ? "https://${var.dashboard_domain}" : "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}

# --- カスタムドメイン用: ../dark-kuins.net-dns の records.yml へ転記する値 ---

output "acm_validation_records" {
  description = "records.yml の acm: セクションへ入れる検証用CNAME(name→value)。まずこれをCloudflareへ。"
  value = local.custom_domain_enabled ? {
    for o in aws_acm_certificate.custom[0].domain_validation_options :
    o.domain_name => {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  } : {}
}

output "dashboard_cname_target" {
  description = "records.yml の cname: に入れる namazu の向き先(CloudFrontドメイン)。"
  value       = local.custom_domain_enabled ? aws_cloudfront_distribution.dashboard.domain_name : null
}

output "api_cname_target" {
  description = "records.yml の cname: に入れる api.namazu の向き先(CloudFrontドメイン)。"
  value       = local.custom_domain_enabled ? aws_cloudfront_distribution.api[0].domain_name : null
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "dashboard_bucket" {
  value = aws_s3_bucket.dashboard.bucket
}

output "dashboard_distribution_id" {
  description = "ダッシュボードのCloudFront Distribution ID。デプロイ後の create-invalidation に使う。"
  value       = aws_cloudfront_distribution.dashboard.id
}
