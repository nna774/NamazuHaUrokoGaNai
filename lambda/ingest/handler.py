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

from batch_uplink import auth, devices, notify, s3util

from common import device_meta, device_temp, events, ota_watch, wire
from jismo.rounding import scale_ordinal

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

# デバイス速報を Slack 通知する最小計測震度(k)。確定報の閾値(l)より高くする想定。
NOTIFY_PROMPT_MIN = float(os.environ.get("NAMZ_NOTIFY_PROMPT_MIN", "3.0"))


def _resp(code: int, msg: str, extra_headers: dict[str, str] | None = None):
    headers = {"content-type": "text/plain"}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": code, "headers": headers, "body": msg}


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
        return _handle_batch(raw, device, headers)
    except Exception as e:  # noqa: BLE001
        print(f"ingest error: {e!r}")
        return _resp(400, f"error: {e}")


def _handle_batch(raw: bytes, auth_device: str, headers: dict[str, str]):
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
    # X-Namz-Fw-Version（batch-uplink v1.6.0のextraRequestHeaders経由、firmwareが
    # 毎バッチ乗せる）は「今このデバイスが動かしている版数」。サーバ側からOTAの
    # 進行状況・停滞原因を見えるようにする（docs/ota.md §7 未決事項1への対応）。
    try:
        devices.record_batch(b.meta.device_id, b.meta.batch_start_us,
                             int(time.time() * 1e6), last_batch_key=key,
                             fw_version=headers.get("x-namz-fw-version", ""))
    except Exception as e:  # noqa: BLE001
        print(f"devices.record_batch failed: {e!r}")

    # センサ種別をデバイス詳細ページ表示用に記録（ヘッダに毎回乗っているので追加コスト無し）。
    try:
        device_meta.record_sensor_type(b.meta.device_id, b.meta.sensor_type)
    except Exception as e:  # noqa: BLE001
        print(f"device_meta.record_sensor_type failed: {e!r}")

    # 温度トレイラーがあれば記録（既に wire.parse 済みなので追加のS3アクセス無し）。
    # ダッシュボードの読み取り側が毎回 raw/ を漁らずに済むよう、書き込み側で1回だけ
    # DynamoDB に残す（docs/log/2026-08-07-device-detail-page-temp-trend.md）。
    if b.meta.sensor_temp_raw is not None:
        try:
            device_temp.record(b.meta.device_id, b.meta.batch_start_us,
                               b.meta.sensor_temp_raw, b.meta.sensor_type)
        except Exception as e:  # noqa: BLE001
            print(f"device_temp.record failed: {e!r}")

    # リモート再起動要求・pull型OTA更新許可をレスポンスへ反映。ここも主経路では
    # ないので、失敗してもバッチ保存自体は成功扱いにする。
    extra_headers: dict[str, str] = {}
    try:
        item = devices.get_device(b.meta.device_id)
        if item:
            # リモート再起動要求（tools/request_restart.py が立てる）は一度伝えたら
            # 消す一回性の要求なので、ヘッダを付けた直後にクリアする。
            if item.get("pending_restart_requested_at_us"):
                extra_headers["X-Namz-Restart"] = "1"
                devices.clear_restart_request(b.meta.device_id)
            # pull型OTA（tools/request_ota.py が立てる、docs/ota.md §7）の許可
            # バージョンは「あるべき状態」なので、再起動要求と違い達成前は
            # クリアしない——デバイスが実際にそのバージョンで起動する（次に
            # NAMZ_FW_VERSIONが一致したバッチを送ってくる）までヘッダを返し
            # 続ける。ダウンロード・書き込み失敗時の自然なリトライにもなる。
            # 一致した後は解放する。さもないとwatchdogの停滞検知（時間経過
            # ベース）が達成後も誤検知し続ける。
            pending_ota = item.get("pending_ota_version")
            if pending_ota:
                if ota_watch.reached_target(item):
                    ota_watch.clear_ota_target(b.meta.device_id, str(pending_ota))
                else:
                    extra_headers["X-Namz-Ota-Version"] = str(pending_ota)
    except Exception as e:  # noqa: BLE001
        print(f"restart/ota request check failed: {e!r}")

    return _resp(200, f"stored {key}", extra_headers or None)


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
