"""ingest Lambda: デバイスからのバッチPOSTと速報アラートを受ける。

Lambda Function URL (payload v2.0) 前提。
- POST /       : 30秒バッチ（application/octet-stream, HMAC署名）→ S3 raw/ へ
- POST /alert  : デバイス速報（JSON, HMAC署名）→ DynamoDB + 即Slack通知
"""

from __future__ import annotations

import base64
import json
import os
import time

import boto3

from common import auth, devices, events, notify, s3util, wire
from jismo.rounding import scale_ordinal

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
            return _handle_alert(raw, device)
        return _handle_batch(raw, device)
    except Exception as e:  # noqa: BLE001
        print(f"ingest error: {e!r}")
        return _resp(400, f"error: {e}")


def _handle_batch(raw: bytes, auth_device: str):
    b = wire.parse(raw)  # magic/長さ検証も兼ねる
    # 認証に使った device と本文の device_id の一致を強制（別デバイスの騙り防止）
    if str(b.meta.device_id) != auth_device:
        return _resp(403, "device mismatch")
    key = s3util.raw_key(b.meta.device_id, b.meta.batch_start_us)
    # 測定開始時刻ベースのキーなので二重送信は同一キー上書き（冪等）
    s3.put_object(Bucket=BUCKET, Key=key, Body=raw,
                  ContentType="application/octet-stream")
    # 生存台帳を更新（watchdog の欠測判定・/devices 表示の元）。ここは主経路ではないので、
    # 失敗してもバッチ保存自体は成功扱いにする（デバイスに無駄な再送をさせない）。
    try:
        devices.record_batch(b.meta.device_id, b.meta.batch_start_us,
                             int(time.time() * 1e6), last_batch_key=key)
    except Exception as e:  # noqa: BLE001
        print(f"devices.record_batch failed: {e!r}")
    return _resp(200, f"stored {key}")


def _handle_alert(raw: bytes, auth_device: str):
    msg = json.loads(raw)
    device_id = int(msg["device_id"])
    if str(device_id) != auth_device:
        return _resp(403, "device mismatch")
    onset_us = int(msg["detected_at_us"])
    intensity = float(msg["realtime_intensity"])
    peak = float(msg["peak_gal"])

    eid, _ = events.record_device_prompt(device_id, onset_us, intensity, peak)
    # イベントは常に記録。通知はセッションの最大震度が「新しい上位クラス」に達し、
    # かつ k 以上の時（弱→強のエスカレーションに追従）。
    item = events.get_event(eid) or {}
    mi = float(item.get("max_intensity", intensity))
    ord_now = scale_ordinal(mi)
    ord_prev = int(item.get("notified_prompt_ord", -1))
    if mi >= NOTIFY_PROMPT_MIN and ord_now > ord_prev:
        notify.from_env().notify(
            "地震かも（デバイス速報）",
            f"デバイスがリアルタイム計測震度 *{mi:.1f}* を検知しました。",
            {"ピーク加速度": f"{peak:.2f} gal", "イベント": notify.event_field(eid)},
        )
        events.set_field(eid, "notified_prompt_ord", ord_now)
    return _resp(200, "alert ok")
