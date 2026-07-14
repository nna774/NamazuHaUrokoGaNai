data "aws_caller_identity" "current" {}

locals {
  name        = var.project
  data_bucket = "${var.project}-data-${data.aws_caller_identity.current.account_id}"
  dash_bucket = "${var.project}-dashboard-${data.aws_caller_identity.current.account_id}"

  lambda_env = {
    NAMZ_BUCKET        = local.data_bucket
    NAMZ_EVENTS_TABLE  = aws_dynamodb_table.events.name
    NAMZ_DEVICES_TABLE = aws_dynamodb_table.devices.name
    # online/offline の境目。api の /devices と watchdog の欠測判定で揃える。
    NAMZ_OFFLINE_AFTER_S = tostring(var.offline_after_seconds)
    # データ遅延の警告値。watchdog の遅延判定と api の /devices（ダッシュボードの
    # 背景色警告）で揃える。
    NAMZ_LAG_AFTER_S = tostring(var.lag_after_seconds)
    NAMZ_DASHBOARD_URL   = local.custom_domain_enabled ? "https://${var.dashboard_domain}" : "https://${aws_cloudfront_distribution.dashboard.domain_name}"
  }
}
