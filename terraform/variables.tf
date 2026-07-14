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

variable "offline_after_seconds" {
  type        = number
  default     = 300
  description = "最終受信からこの秒数を超えたら欠測とみなす。バッチは30秒間隔なので既定300秒＝約10バッチ落ち。"
}

variable "offline_renotify_seconds" {
  type        = number
  default     = 86400
  description = "欠測が続いている間に通知を再送する間隔[秒]。既定1日。"
}

variable "lag_after_seconds" {
  type        = number
  default     = 600
  description = "受信は続いているが測定時刻がこの秒数以上遅れたら「データ遅延」を通知する。既定600秒＝10分。"
}

variable "lag_renotify_seconds" {
  type        = number
  default     = 86400
  description = "データ遅延が続いている間に通知を再送する間隔[秒]。既定1日。"
}

variable "watchdog_schedule" {
  type        = string
  default     = "rate(5 minutes)"
  description = "欠測監視 watchdog の起動間隔（EventBridge schedule expression）。通知の遅れ ≒ 欠測しきい値 + この間隔。どの頻度でも無料枠に収まるので、遅さの許容度で決める。"
}
