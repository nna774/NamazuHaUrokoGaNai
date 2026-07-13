variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "namazu"
}

variable "dashboard_domain" {
  type        = string
  default     = "namazu.dark-kuins.net"
  description = "ダッシュボードのカスタムドメイン。CloudFrontのaliasにする。空ならCloudFront既定ドメイン+既定証明書のまま。"
}

variable "api_domain" {
  type        = string
  default     = "api.namazu.dark-kuins.net"
  description = "読み取りAPIのカスタムドメイン。Function URLを前段CloudFrontで包んでaliasにする。空ならFunction URLのまま。"
}

variable "raw_retention_days" {
  type        = number
  default     = 90
  description = "raw/ の保持日数。これを過ぎたら削除（イベント周辺は events/ に永久保存）。"
}

variable "hmac_secret" {
  type        = string
  sensitive   = true
  description = "デバイスと共有する HMAC 鍵。firmware secrets.h と一致させる。"
}

variable "slack_webhook_url" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Slack Incoming Webhook URL。空なら通知しない。"
}

variable "slack_channel" {
  type        = string
  default     = ""
  description = "通知先チャンネル（例 #nona-kanshi）。レガシーwebhookでのみ上書き可。空ならwebhook既定先。"
}

variable "detect_threshold" {
  type    = number
  default = 0.5
}

variable "detect_hold_seconds" {
  type    = number
  default = 2.0
}

variable "detect_window_seconds" {
  type    = number
  default = 120
}

variable "notify_prompt_min" {
  type        = number
  default     = 3.0
  description = "デバイス速報を通知する最小計測震度(k)。確定報の閾値(l)より高くする。"
}

variable "notify_confirm_min" {
  type        = number
  default     = 1.5
  description = "確定報を通知する最小計測震度(l)。k > l。"
}
