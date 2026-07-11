output "ingest_url" {
  description = "firmware secrets.h の kIngestUrl。/alert を付けたものが kAlertUrl。"
  value       = aws_lambda_function_url.ingest.function_url
}

output "api_url" {
  description = "ダッシュボードが叩く読み取りAPIのURL。"
  value       = aws_lambda_function_url.api.function_url
}

output "dashboard_url" {
  description = "ダッシュボードの公開URL。"
  value       = "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "dashboard_bucket" {
  value = aws_s3_bucket.dashboard.bucket
}
