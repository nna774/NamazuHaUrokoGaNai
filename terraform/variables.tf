variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "namazu"
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
