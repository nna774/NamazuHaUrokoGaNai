"""detect Lambda: raw/ へのバッチ到着ごとに直近窓を再解析し、地震を確定検知する。

- S3 の ObjectCreated(raw/*) で起動
- 直近 WINDOW_SECONDS 秒を連結して計測震度を再計算
- 閾値以上が継続する揺れがあれば:
    - イベント波形を events/<id>/ へコピー（永久保存）
    - DynamoDB に確定報を記録（デバイス速報と突合）
    - まだ確定通知していなければ Slack 通知（確定報）
"""

from __future__ import annotations

import json
import os
from urllib.parse import unquote_plus

import boto3

from common import detect_core, events, notify, s3util, store
from jismo.rounding import intensity_scale

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

WINDOW_SECONDS = float(os.environ.get("NAMZ_DETECT_WINDOW_S", "120"))
THRESHOLD = float(os.environ.get("NAMZ_DETECT_THRESHOLD", "0.5"))
HOLD_SECONDS = float(os.environ.get("NAMZ_DETECT_HOLD_S", "2.0"))
# イベント波形として保存する範囲（onset を基準に前後）
PRE_SECONDS = 30
POST_SECONDS = 90


def handler(event, context):
    for rec in event.get("Records", []):
        key = unquote_plus(rec["s3"]["object"]["key"])
        if not key.startswith(f"{s3util.RAW_PREFIX}/"):
            continue
        try:
            _process(key)
        except Exception as e:  # noqa: BLE001
            print(f"detect error on {key}: {e!r}")


def _process(key: str):
    b = store.get_batch(s3, BUCKET, key)
    batch_len_us = int(b.meta.sample_count / b.meta.sample_rate_hz * 1e6)
    end_us = b.meta.batch_start_us + batch_len_us

    gal, win_start, fs = store.load_window(s3, BUCKET, end_us, WINDOW_SECONDS)
    if gal.shape[0] == 0:
        return

    det = detect_core.analyze(gal, fs, win_start, THRESHOLD, HOLD_SECONDS)
    if det is None:
        return

    device_id = b.meta.device_id
    eid = events.event_id(device_id, det.onset_us)
    existing = events.get_event(eid)
    already_confirmed = bool(existing and existing.get("cloud_confirmed"))

    prefix = f"{s3util.EVENTS_PREFIX}/{eid}/"
    _copy_event_waveforms(eid, det.onset_us)
    _write_event_meta(eid, device_id, det)

    events.record_cloud_detection(device_id, det.onset_us, det.max_intensity,
                                  det.peak_gal, prefix)

    if not already_confirmed:
        scale = intensity_scale(det.max_intensity)
        notify.from_env().notify(
            f"地震を検知（確定報） 震度{scale}",
            f"クラウド解析で計測震度 *{det.max_intensity:.1f}*（震度{scale}）を確定。",
            {"ピーク加速度": f"{det.peak_gal:.2f} gal",
             "波形": prefix, "event": eid},
        )


def _copy_event_waveforms(eid: str, onset_us: int):
    """onset 周辺の raw バッチを events/<id>/ へコピー（永久保存）。"""
    start_us = int(onset_us - PRE_SECONDS * 1e6)
    end_us = int(onset_us + POST_SECONDS * 1e6)
    for key in store.list_raw_keys_in_range(s3, BUCKET, start_us, end_us):
        # ファイル名末尾の startus で範囲判定
        try:
            b_start = int(key.rsplit("-", 1)[1].split(".")[0])
        except (IndexError, ValueError):
            continue
        if b_start < start_us - 30_000_000 or b_start > end_us:
            continue
        dst = s3util.event_batch_key(eid, b_start)
        s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": key}, Key=dst)


def _write_event_meta(eid: str, device_id: int, det: detect_core.Detection):
    meta = {
        "event_id": eid,
        "device_id": device_id,
        "onset_us": det.onset_us,
        "max_intensity": det.max_intensity,
        "scale": intensity_scale(det.max_intensity),
        "peak_gal": det.peak_gal,
        "a0_gal": det.a0,
    }
    s3.put_object(Bucket=BUCKET, Key=s3util.event_meta_key(eid),
                  Body=json.dumps(meta, ensure_ascii=False).encode(),
                  ContentType="application/json")
