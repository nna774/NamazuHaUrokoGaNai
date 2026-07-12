"""api Lambda: ダッシュボード向けの読み取りAPI（認証なし・CORS許可）。

Lambda Function URL (payload v2.0)。
- GET /recent?minutes=5&device=1  直近n分の波形（大きい範囲はmin/maxエンベロープに間引き）
- GET /events                     イベント一覧
- GET /event?id=<event_id>        イベントのメタ + 波形
"""

from __future__ import annotations

import json
import os
import time

import boto3
import numpy as np

from common import events, s3util, store, wire
from jismo.rounding import intensity_scale

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

MAX_POINTS = 3000
# CORSヘッダは Function URL の cors 設定に任せる（ここで access-control-* を
# 返すと Function URL のぶんと二重になり、ブラウザが弾く）。ここは content-type のみ。
HEADERS = {"content-type": "application/json"}


def _json(code: int, obj) -> dict:
    return {"statusCode": code, "headers": HEADERS, "body": json.dumps(obj, default=_default)}


def _default(o):
    from decimal import Decimal
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    raise TypeError(type(o))


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": {}, "body": ""}
    path = event.get("rawPath", "/").rstrip("/")
    q = event.get("queryStringParameters") or {}
    try:
        if path.endswith("/recent"):
            return _recent(q)
        if path.endswith("/events"):
            return _events(q)
        if path.endswith("/event"):
            return _event(q)
        return _json(404, {"error": "not found"})
    except Exception as e:  # noqa: BLE001
        print(f"api error: {e!r}")
        return _json(500, {"error": str(e)})


def _recent(q):
    minutes = float(q.get("minutes", "5"))
    end_us = int(time.time() * 1e6)
    gal, win_start, fs = store.load_window(s3, BUCKET, end_us, minutes * 60)
    return _json(200, _waveform_payload(gal, win_start, fs))


def _events(q):
    page = max(0, int(q.get("page", "0")))
    size = min(100, max(1, int(q.get("size", "20"))))
    show_all = q.get("all") in ("1", "true")
    items, total = events.list_page(page, size, show_all=show_all)
    # 一覧・詳細で同じ値を出すため、震度は effective_intensity に統一する。
    for it in items:
        eff = events.effective_intensity(it)
        it["max_intensity"] = eff
        it["scale"] = intensity_scale(eff)
    return _json(200, {"events": items, "page": page, "size": size, "total": total})


def _event(q):
    eid = q.get("id")
    if not eid:
        return _json(400, {"error": "missing id"})
    # meta.json があれば波形付き（クラウド確定済イベント）。
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=s3util.event_meta_key(eid))
        meta = json.loads(obj["Body"].read())
        # 一覧と同じ effective_intensity に揃える（meta.jsonの値より優先）。
        item = events.get_event(eid)
        if item:
            eff = events.effective_intensity(item)
            meta["max_intensity"] = eff
            meta["scale"] = intensity_scale(eff)
    except s3.exceptions.NoSuchKey:
        # 速報のみのイベントは波形コピーが無い。DynamoDBの情報だけ返す。
        item = events.get_event(eid)
        if item is None:
            return _json(404, {"error": "event not found"})
        intensity = float(item.get("max_intensity", 0))
        meta = {
            "event_id": eid,
            "onset_us": int(item.get("onset_us", 0)),
            "max_intensity": intensity,
            "scale": intensity_scale(intensity),
            "peak_gal": float(item.get("peak_gal", 0)),
            "device_prompt": bool(item.get("device_prompt")),
            "cloud_confirmed": bool(item.get("cloud_confirmed")),
            "note": "速報のみ（波形の永久保存なし）。raw/が残っていればライブ表示で遡れる。",
        }
        return _json(200, {"meta": meta, "waveform": _waveform_payload(np.empty((0, 3)), meta["onset_us"], 100.0)})
    # 波形（events/<id>/*.bin を連結）
    parts, win_start, fs = [], None, 100.0
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{s3util.EVENTS_PREFIX}/{eid}/")
    keys = sorted(it["Key"] for it in resp.get("Contents", []) if it["Key"].endswith(".bin"))
    for key in keys:
        b = wire.parse(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
        if win_start is None:
            win_start = b.meta.batch_start_us
        fs = b.meta.sample_rate_hz
        parts.append(b.gal)
    gal = np.concatenate(parts, axis=0) if parts else np.empty((0, 3))
    payload = _waveform_payload(gal, win_start or meta.get("onset_us", 0), fs)
    return _json(200, {"meta": meta, "waveform": payload})


def _waveform_payload(gal: np.ndarray, start_us: int, fs: float) -> dict:
    n = gal.shape[0]
    if n == 0:
        return {"mode": "raw", "fs": fs, "start_us": start_us, "n": 0,
                "x": [], "y": [], "z": []}
    if n <= MAX_POINTS:
        return {
            "mode": "raw", "fs": fs, "start_us": int(start_us), "n": n,
            "x": _round(gal[:, 0]), "y": _round(gal[:, 1]), "z": _round(gal[:, 2]),
        }
    # min/max エンベロープに間引き
    bucket = int(np.ceil(n / MAX_POINTS))
    m = (n // bucket) * bucket
    g = gal[:m].reshape(-1, bucket, 3)
    out = {"mode": "envelope", "fs": fs, "start_us": int(start_us),
           "n": g.shape[0], "bucket": bucket}
    for i, ax in enumerate("xyz"):
        out[f"{ax}_min"] = _round(g[:, :, i].min(axis=1))
        out[f"{ax}_max"] = _round(g[:, :, i].max(axis=1))
    return out


def _round(arr: np.ndarray) -> list:
    return [round(float(v), 4) for v in arr]
