"""ingest Lambda: デバイスからのバッチPOSTと速報アラートを受ける。

Lambda Function URL (payload v2.0) 前提。
- POST /       : 30秒バッチ（application/octet-stream, HMAC署名）→ S3 raw/ へ
- POST /alert  : デバイス速報（JSON, HMAC署名）→ DynamoDB + 即Slack通知
"""

from __future__ import annotations

import base64
import json
import os

import boto3

from common import auth, events, notify, s3util, wire

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

# デバイス速報を Slack 通知する最小計測震度(k)。確定報の閾値(l)より高くする想定。
NOTIFY_PROMPT_MIN = float(os.environ.get("NAMZ_NOTIFY_PROMPT_MIN", "3.0"))


def _resp(code: int, msg: str):
    return {"statusCode": code, "headers": {"content-type": "text/plain"}, "body": msg}


def handler(event, context):
    path = event.get("rawPath", "/")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()

    device = headers.get("x-namz-device", "")
    sig = headers.get("x-namz-signature", "")
    try:
        auth.verify(device, raw, sig)
    except auth.AuthError as e:
        return _resp(401, f"auth: {e}")

    try:
        if path.rstrip("/").endswith("alert"):
            return _handle_alert(raw)
        return _handle_batch(raw)
    except Exception as e:  # noqa: BLE001
        print(f"ingest error: {e!r}")
        return _resp(400, f"error: {e}")


def _handle_batch(raw: bytes):
    b = wire.parse(raw)  # magic/長さ検証も兼ねる
    key = s3util.raw_key(b.meta.device_id, b.meta.batch_start_us)
    # 測定開始時刻ベースのキーなので二重送信は同一キー上書き（冪等）
    s3.put_object(Bucket=BUCKET, Key=key, Body=raw,
                  ContentType="application/octet-stream")
    return _resp(200, f"stored {key}")


def _handle_alert(raw: bytes):
    msg = json.loads(raw)
    device_id = int(msg["device_id"])
    onset_us = int(msg["detected_at_us"])
    intensity = float(msg["realtime_intensity"])
    peak = float(msg["peak_gal"])

    eid, is_new = events.record_device_prompt(device_id, onset_us, intensity, peak)
    # イベントは常に記録するが、通知は閾値k以上かつセッション開始時のみ。
    if is_new and intensity >= NOTIFY_PROMPT_MIN:
        notify.from_env().notify(
            "地震かも（デバイス速報）",
            f"デバイスがリアルタイム計測震度 *{intensity:.1f}* を検知しました。",
            {"ピーク加速度": f"{peak:.2f} gal", "イベント": notify.event_field(eid)},
        )
    return _resp(200, "alert ok")
