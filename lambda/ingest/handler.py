"""ingest Lambda: デバイスからのバッチPOST・速報アラート・coredumpを受ける。

Lambda Function URL (payload v2.0) 前提。
- POST /          : 30秒バッチ（application/octet-stream, HMAC署名）→ S3 raw/ へ
- POST /alert     : デバイス速報（JSON, HMAC署名）→ DynamoDB + 即Slack通知
- POST /coredump  : 起動時に見つかったコアダンプ（application/octet-stream, HMAC署名）
                    → S3 coredump/ へ（docs/log/2026-08-29-coredump-auto-upload-plan.md）
"""

from __future__ import annotations

import base64
import json
import os
import time

import boto3

from batch_uplink import auth, devices, notify

from common import (device_meta, device_temp, dynamo_update, events, metrics, ota_watch,
                     s3util, watchdog_mute, wire)
from jismo.rounding import scale_ordinal

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]
_devices_table = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])

# デバイス速報を Slack 通知する最小計測震度(k)。確定報の閾値(l)より高くする想定。
NOTIFY_PROMPT_MIN = float(os.environ.get("NAMZ_NOTIFY_PROMPT_MIN", "3.0"))

# watchdog(lambda/watchdog/handler.py)と同じメンション先。coredumpは再起動原因の
# 調査を促す通知なので、欠測アラートと同じ人に飛ばす。
SLACK_MENTION = "<@U0323ESK6> "


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
        p = path.rstrip("/")
        if p.endswith("alert"):
            return _handle_alert(raw, device)
        if p.endswith("coredump"):
            return _handle_coredump(raw, device, headers)
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
    # 生存台帳の現在値を先に1回だけ読む。record_batch_fragments()のlast_batch_start_us
    # 単調性判断と、後段の再起動/OTA/起動検知の判定の両方でこの1回のGetItemを使い回す
    # （docs/log/2026-08-23-devices-batch-uplink-consolidation.md）。ここは主経路では
    # ないので、失敗してもバッチ保存自体は成功扱いにする（デバイスに無駄な再送をさせない）。
    item = None
    try:
        item = devices.get_device(b.meta.device_id)
    except Exception as e:  # noqa: BLE001
        print(f"devices.get_device failed: {e!r}")

    # X-Namz-Fw-Version（batch-uplink v1.6.0のextraRequestHeaders経由、firmwareが
    # 毎バッチ乗せる）は「今このデバイスが動かしている版数」。サーバ側からOTAの
    # 進行状況・停滞原因を見えるようにする（docs/ota.md §2 未決事項1への対応）。
    # record_batch_fragments()（batch-uplink v3.2.0〜）・mute解除・センサ種別は
    # 同一項目への書き込みなので、各モジュールが実行しない断片だけを返し、ここで
    # 集約して1回のupdate_itemにまとめる（関心事が増えても組み合わせ専用関数を
    # 書かずに済む）。
    try:
        builder = dynamo_update.UpdateItemBuilder()
        for expr, values in devices.record_batch_fragments(
                item, b.meta.batch_start_us, int(time.time() * 1e6),
                last_batch_key=key, fw_version=headers.get("x-namz-fw-version", "")):
            builder.add(expr, values)
        builder.add(*watchdog_mute.clear_mute_fragment())
        builder.add(*device_meta.sensor_type_fragment(b.meta.sensor_type))
        builder.execute(_devices_table, b.meta.device_id)
    except Exception as e:  # noqa: BLE001
        print(f"devices update failed: {e!r}")

    # 温度トレイラーがあれば記録（既に wire.parse 済みなので追加のS3アクセス無し）。
    # ダッシュボードの読み取り側が毎回 raw/ を漁らずに済むよう、書き込み側で1回だけ
    # DynamoDB に残す（docs/log/2026-08-07-device-detail-page-temp-trend.md）。
    if b.meta.sensor_temp_raw is not None:
        try:
            device_temp.record(b.meta.device_id, b.meta.batch_start_us,
                               b.meta.sensor_temp_raw, b.meta.sensor_type)
        except Exception as e:  # noqa: BLE001
            print(f"device_temp.record failed: {e!r}")

    # ヒープ空き容量ヘッダ(X-Namz-Heap-Free/-Maxblock、docs/design.md「送信の
    # 信頼性」未定事項4)をCloudWatchカスタムメトリクスへ送る。TLS接続使い回し
    # (v1.7.0)がバックフィル中の断片化にどう効くか、実機のシリアルログ無しでも
    # 事後に推移で追えるようにするための可観測性。
    heap_free_raw = headers.get("x-namz-heap-free", "")
    heap_maxblock_raw = headers.get("x-namz-heap-maxblock", "")
    if heap_free_raw and heap_maxblock_raw:
        try:
            metrics.record_heap(b.meta.device_id, int(heap_free_raw), int(heap_maxblock_raw))
        except Exception as e:  # noqa: BLE001
            print(f"metrics.record_heap failed: {e!r}")

    # 未送信バックログ件数ヘッダ(X-Namz-Spill-Count/-Ram-Queued)をCloudWatchへ送る。
    # これまでデバイス本体のOLED表示にしか出ていなかった滞留量(spill=LittleFS退避済み・
    # ram=RAMキュー内)を、サーバ側からも見えるようにする(memo.md「batch okuru toki
    # spill youryou mo issyo ni okurenaika」への対応)。
    spill_count_raw = headers.get("x-namz-spill-count", "")
    ram_queued_raw = headers.get("x-namz-ram-queued", "")
    if spill_count_raw and ram_queued_raw:
        try:
            metrics.record_backlog(b.meta.device_id, int(spill_count_raw), int(ram_queued_raw))
        except Exception as e:  # noqa: BLE001
            print(f"metrics.record_backlog failed: {e!r}")

    # リモート再起動要求・pull型OTA更新許可をレスポンスへ反映。上で取得したitemを使い回す
    # （このバッチ書き込みはpending_restart_requested_at_us/pending_ota_versionに触れない
    # ので、書き込みの前後で値は変わらない）。ここも主経路ではないので、失敗しても
    # バッチ保存自体は成功扱いにする。
    extra_headers: dict[str, str] = {}
    try:
        if item:
            # リモート再起動要求（tools/request_restart.py が立てる）は一度伝えたら
            # 消す一回性の要求なので、ヘッダを付けた直後にクリアする。
            if item.get("pending_restart_requested_at_us"):
                extra_headers["X-Namz-Restart"] = "1"
                devices.clear_restart_request(b.meta.device_id)
            # pull型OTA（tools/request_ota.py が立てる、docs/ota.md §2）の許可
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

    # 稼働時間ヘッダ(X-Namz-Uptime-Us、docs/uptime.md §2.2)から起動時刻を逆算し、
    # 前回保存値からTimeSyncドリフト許容(±2分)を超えてズレていたら再起動とみなして
    # 記録する。raw/には残さず、その場で使い切る（wire v2トレイラーではなくヘッダに
    # した理由そのもの）。
    uptime_raw = headers.get("x-namz-uptime-us", "")
    if uptime_raw:
        try:
            boot_epoch_us = b.meta.batch_start_us - int(uptime_raw)
            prev = item.get("boot_epoch_us") if item else None
            if device_meta.should_update_boot_epoch(prev, boot_epoch_us):
                # X-Namz-Reset-Reason(esp_reset_reason())は再起動を検知した
                # 瞬間にしか意味が無いので、ここでしか読まない。
                device_meta.record_boot_epoch(
                    b.meta.device_id, boot_epoch_us,
                    reset_reason=headers.get("x-namz-reset-reason", ""))
        except Exception as e:  # noqa: BLE001
            print(f"device_meta.record_boot_epoch failed: {e!r}")

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


def _handle_coredump(raw: bytes, auth_device: str, headers: dict[str, str]):
    # コアダンプ本体はwire formatを持たない生バイナリなので、device_idは(認証済みの)
    # X-Namz-Deviceヘッダだけが情報源(バッチ/速報のような本文とのdevice_id一致検証は
    # 元々できない)。
    device_id = int(auth_device)
    fw_version = headers.get("x-namz-fw-version", "unknown")
    uploaded_at_us = int(time.time() * 1e6)
    key = s3util.coredump_key(device_id, fw_version, uploaded_at_us)
    s3.put_object(Bucket=BUCKET, Key=key, Body=raw, ContentType="application/octet-stream")

    # 通知は主経路ではないので、S3保存が済んでいれば失敗してもACK(200)は返す
    # （_handle_batchのdevices.get_device失敗時と同じ扱い）。
    try:
        notify.from_env().notify(
            f"{SLACK_MENTION}コアダンプを回収した",
            f"device *{device_id:04d}* (fw={fw_version}) の起動時にコアダンプが見つかり、"
            "S3へ保存した。再起動原因の調査に使える。",
            {"S3キー": key},
        )
    except Exception as e:  # noqa: BLE001
        print(f"coredump notify failed: {e!r}")

    return _resp(200, f"stored {key}")
