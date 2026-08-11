# イベントはS3のraw/と違って唯一の原本（再生成不可）。誤ってDeleteTableされる事故を
# AWS側で拒否させる（Terraform経由でなくAWS CLI/コンソールから直接叩かれても効く）。
# 本当に消す時はこの属性をfalseにしてからでないとDeleteTableが通らない。
resource "aws_dynamodb_table" "events" {
  name                        = "${local.name}-events"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "event_id"
  deletion_protection_enabled = true

  attribute {
    name = "event_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# デバイスの生存台帳。ingest が受信ごとに upsert し、watchdog が欠測を判定、
# api /devices が読む。「今このデバイスが喋っているか」の単一の真実。
resource "aws_dynamodb_table" "devices" {
  name         = "${local.name}-devices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"

  attribute {
    name = "device_id"
    type = "N"
  }
}

# センサ内蔵温度の時系列。ingest が受信バッチごとに1件書き（wire.parse 済みなので
# 追加のS3アクセス無し）、api /devices/<id>/temp が device_id + 時刻レンジで Query する。
# 波形と違い読み取り側でS3を漁らないので、公開読み取りAPIを叩かれても課金が
# 増えにくい（docs/log/2026-08-07-device-detail-page-temp-trend.md）。
resource "aws_dynamodb_table" "device_temp" {
  name         = "${local.name}-device-temp"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"
  range_key    = "batch_start_us"

  attribute {
    name = "device_id"
    type = "N"
  }

  attribute {
    name = "batch_start_us"
    type = "N"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
