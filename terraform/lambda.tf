# zip は ./build_lambda.sh が terraform/builds/<fn>.zip に生成する。
# apply 前に必ず ./build_lambda.sh を実行すること。
locals {
  build_dir = "${path.module}/builds"
  common_env = merge(local.lambda_env, {
    NAMZ_HMAC_SECRET        = var.hmac_secret
    NAMZ_SLACK_WEBHOOK_URL  = var.slack_webhook_url
    NAMZ_NOTIFY_PROMPT_MIN  = tostring(var.notify_prompt_min)
    NAMZ_NOTIFY_CONFIRM_MIN = tostring(var.notify_confirm_min)
  })
}

# --- ingest ---
resource "aws_lambda_function" "ingest" {
  function_name    = "${local.name}-ingest"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/ingest.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/ingest.zip"), null)
  timeout          = 15
  memory_size      = 256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function_url" "ingest" {
  function_name      = aws_lambda_function.ingest.function_name
  authorization_type = "NONE" # 認証はアプリ層のHMACで行う
}

# --- detect ---
resource "aws_lambda_function" "detect" {
  function_name    = "${local.name}-detect"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/detect.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/detect.zip"), null)
  timeout          = 60
  memory_size      = 512

  environment {
    variables = merge(local.common_env, {
      NAMZ_DETECT_THRESHOLD = tostring(var.detect_threshold)
      NAMZ_DETECT_HOLD_S    = tostring(var.detect_hold_seconds)
      NAMZ_DETECT_WINDOW_S  = tostring(var.detect_window_seconds)
    })
  }
}

resource "aws_lambda_permission" "detect_from_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detect.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.data.arn
}

# --- api ---
resource "aws_lambda_function" "api" {
  function_name    = "${local.name}-api"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  filename         = "${local.build_dir}/api.zip"
  source_code_hash = try(filebase64sha256("${local.build_dir}/api.zip"), null)
  timeout          = 30
  memory_size      = 512

  environment {
    variables = local.lambda_env
  }
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE" # ダッシュボードは認証なし

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET"]
  }
}
