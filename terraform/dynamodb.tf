resource "aws_dynamodb_table" "events" {
  name         = "${local.name}-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
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
