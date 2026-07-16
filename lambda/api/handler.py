"""api Lambda: ダッシュボード向けの読み取りAPI（認証なし・CORS許可）。

Lambda Function URL (payload v2.0)。
- GET /recent?minutes=5&start=<us> 波形。start指定で[start,start+minutes]、無指定で直近n分
                                   （大きい範囲はmin/maxエンベロープに間引き）
- GET /events                     イベント一覧
- GET /event?id=<event_id>        イベントのメタ + 波形
      &from=<us>&to=<to>          任意。保存済み波形からこの区間だけ切り出して返す
                                  （ダッシュボードのズームが狭い区間のrawを取り直す用）
"""

from __future__ import annotations

import json
import math
import os
import re
import time

import boto3
import numpy as np

from common import devices, events, s3util, store, wire
from jismo.rounding import intensity_scale

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

# online/offline の境目。watchdog の欠測しきい値と揃える（同じ env を両者に渡す）。
OFFLINE_AFTER_S = float(os.environ.get("NAMZ_OFFLINE_AFTER_S", "300"))
# データ遅延の警告値。watchdog の遅延判定と揃える。ダッシュボードの背景色警告に使う。
LAG_AFTER_S = float(os.environ.get("NAMZ_LAG_AFTER_S", "600"))
MAX_POINTS = 3000
# /recent の分数上限。上限が無いと巨大値でS3 LIST/GETを大量発行して
# ハング/課金する（認証なし公開のため要ガード）。UIの選択肢も30分まで。
MAX_RECENT_MINUTES = 30.0
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
        m = re.search(r"/devices/(\d{1,4})$", path)  # 個別デバイス（より具体的な方を先に）
        if m:
            return _device(int(m.group(1)))
        if path.endswith("/devices"):
            return _devices()
        return _json(404, {"error": "not found"})
    except Exception as e:  # noqa: BLE001
        print(f"api error: {e!r}")
        return _json(500, {"error": str(e)})


def _recent(q):
    try:
        minutes = float(q.get("minutes", "5"))
    except (TypeError, ValueError):
        minutes = 5.0
    if not math.isfinite(minutes):
        minutes = 5.0
    minutes = max(0.1, min(minutes, MAX_RECENT_MINUTES))  # 巨大値によるS3スキャン暴走を防ぐ
    # start 指定時は [start, start+minutes] を、無指定なら [now-minutes, now] を返す。
    # 窓幅は minutes（最大30分）で頭打ちなので、start をどこに置いてもS3スキャン量は
    # 一定に収まる（認証なし公開のガードは minutes 上限だけで足りる）。
    span_us = int(minutes * 60 * 1e6)
    end_us = int(time.time() * 1e6)
    start = q.get("start")
    if start:
        try:
            end_us = int(float(start)) + span_us
        except (TypeError, ValueError):
            pass
    gal, win_start, fs = store.load_window(s3, BUCKET, end_us, minutes * 60)
    return _json(200, _waveform_payload(gal, win_start, fs))


def _int_param(q, name, default, lo, hi):
    """クエリの整数パラメータを安全にパースし [lo, hi] にクランプする。"""
    try:
        v = int(q.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(v, hi))


def _events(q):
    page = _int_param(q, "page", 0, 0, 100000)
    size = _int_param(q, "size", 20, 1, 100)
    show_all = q.get("all") in ("1", "true")
    items, total = events.list_page(page, size, show_all=show_all)
    # 一覧・詳細で同じ値を出すため、震度は effective_intensity に統一する。
    for it in items:
        eff = events.effective_intensity(it)
        it["max_intensity"] = eff
        it["scale"] = intensity_scale(eff)
    return _json(200, {"events": items, "page": page, "size": size, "total": total})


def _event(q):
    eid = q.get("id", "")
    # event_id は「デバイス4桁-バケット数値」形式のみ。S3キーに埋め込むため書式を強制する。
    if not re.fullmatch(r"\d{4}-\d{1,16}", eid):
        return _json(400, {"error": "bad id"})
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
            meta["last_us"] = int(item.get("last_us", meta.get("onset_us", 0)))
            meta["device_prompt"] = bool(item.get("device_prompt"))
            meta["cloud_confirmed"] = bool(item.get("cloud_confirmed"))
            meta["checked"] = bool(item.get("checked"))
            meta["artificial"] = bool(item.get("artificial"))
    except s3.exceptions.NoSuchKey:
        # 速報のみのイベントは波形コピーが無い。DynamoDBの情報だけ返す。
        item = events.get_event(eid)
        if item is None:
            return _json(404, {"error": "event not found"})
        intensity = float(item.get("max_intensity", 0))
        meta = {
            "event_id": eid,
            "onset_us": int(item.get("onset_us", 0)),
            "last_us": int(item.get("last_us", item.get("onset_us", 0))),
            "max_intensity": intensity,
            "scale": intensity_scale(intensity),
            "peak_gal": float(item.get("peak_gal", 0)),
            "device_prompt": bool(item.get("device_prompt")),
            "cloud_confirmed": bool(item.get("cloud_confirmed")),
            "checked": bool(item.get("checked")),
            "artificial": bool(item.get("artificial")),
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
    win_start = win_start or meta.get("onset_us", 0)
    # from/to 指定があれば区間を切り出す。狭い区間なら MAX_POINTS に収まり raw で返るので、
    # ダッシュボードのズームがエンベロープ(間引き)から100Hz生波形に切り替えられる。
    gal, win_start = _slice_gal(gal, win_start, fs, q.get("from"), q.get("to"))
    payload = _waveform_payload(gal, win_start, fs)
    return _json(200, {"meta": meta, "waveform": payload})


def _slice_gal(gal: np.ndarray, win_start: int, fs: float, frm, to):
    """波形から [frm, to] (us) の区間を切り出す。不正・範囲外はクランプし、
    パース不能や区間が実質空なら全体をそのまま返す。"""
    if gal.shape[0] == 0 or frm is None or to is None:
        return gal, win_start
    try:
        f_us, t_us = int(float(frm)), int(float(to))
    except (TypeError, ValueError):
        return gal, win_start
    if t_us <= f_us:
        return gal, win_start
    i0 = max(0, int((f_us - win_start) * fs / 1e6))
    i1 = min(gal.shape[0], int(math.ceil((t_us - win_start) * fs / 1e6)) + 1)
    if i1 - i0 < 2:  # 端の外を指す等で実質空 → 全体を返す（クライアントは何かしら描ける）
        return gal, win_start
    return gal[i0:i1], win_start + int(i0 / fs * 1e6)


def _device_view(item: dict, now_us: int) -> dict:
    """デバイス台帳の1項目を、表示向けに整形する（経過秒・online 判定を付ける）。"""
    last = int(item.get("last_ingest_at_us", 0))
    age_us = (now_us - last) if last else None
    last_batch = int(item.get("last_batch_start_us", 0))
    return {
        "device_id": int(item.get("device_id", 0)),
        "last_ingest_at_us": last,
        "last_batch_start_us": last_batch,
        "batches_total": int(item.get("batches_total", 0)),
        "last_batch_key": item.get("last_batch_key", ""),
        # 生存は受信壁時計で、データ遅延は測定時刻で（バックフィル対策）。
        "age_s": (age_us / 1e6) if age_us is not None else None,
        "lag_s": ((now_us - last_batch) / 1e6) if last_batch else None,
        "online": age_us is not None and age_us <= int(OFFLINE_AFTER_S * 1e6),
    }


def _devices():
    now_us = int(time.time() * 1e6)
    items = [_device_view(it, now_us) for it in devices.list_devices()]
    return _json(200, {"devices": items, "offline_after_s": OFFLINE_AFTER_S,
                       "lag_after_s": LAG_AFTER_S})


def _device(device_id: int):
    now_us = int(time.time() * 1e6)
    item = devices.get_device(device_id)
    if item is None:
        return _json(404, {"error": "device not found"})
    return _json(200, {"device": _device_view(item, now_us),
                       "offline_after_s": OFFLINE_AFTER_S,
                       "lag_after_s": LAG_AFTER_S})


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
