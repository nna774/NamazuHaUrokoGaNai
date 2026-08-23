"""api Lambda: ダッシュボード向けの読み取りAPI（認証なし・CORS許可）。

Lambda Function URL (payload v2.0)。
- GET /recent?minutes=5&start=<us> 波形。start指定で[start,start+minutes]、無指定で直近n分
                                   （大きい範囲はmin/maxエンベロープに間引き）
- GET /events?device=<id>         イベント一覧（device無指定は全デバイス）
- GET /event?id=<event_id>        イベントのメタ + 波形
      &from=<us>&to=<to>          任意。保存済み波形からこの区間だけ切り出して返す
                                  （ダッシュボードのズームが狭い区間のrawを取り直す用）
- GET /devices/<id>/temp?hours=<n> センサ内蔵温度の時系列（デバイス詳細ページ用）
"""

from __future__ import annotations

import json
import math
import os
import re
import time

import boto3
import numpy as np

from batch_uplink import devices

from common import device_temp, events, metrics, s3util, store, watchdog_mute, wire
from jismo.rounding import intensity_scale

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

# online/offline の境目。watchdog の欠測しきい値と揃える（同じ env を両者に渡す）。
OFFLINE_AFTER_S = float(os.environ.get("NAMZ_OFFLINE_AFTER_S", "300"))
# データ遅延の警告値。watchdog の遅延判定と揃える。ダッシュボードの背景色警告に使う。
LAG_AFTER_S = float(os.environ.get("NAMZ_LAG_AFTER_S", "600"))
# 6000 = 1分@100Hz。ライブ画面の既定窓(1分)をrawのまま返すための値
# （ダッシュボードがクライアント側で概算震度を計算するには生サンプルが要る。
# dashboard/app.js の EVENT_RAW_MAX_POINTS と一致させること）。
# S3読み出し量は minutes(上限30分)で決まりこれとは無関係なので、上げてもスキャンは増えない。
MAX_POINTS = 6000
# /recent の分数上限。上限が無いと巨大値でS3 LIST/GETを大量発行して
# ハング/課金する（認証なし公開のため要ガード）。UIの選択肢も30分まで。
MAX_RECENT_MINUTES = 30.0
# /devices/<id>/temp の時間窓上限と間引き点数上限。DynamoDB Query なので /recent の
# S3スキャンほど窓を絞る必要はないが、上限はUIの選択肢(24時間)に合わせて置いておく。
MAX_TEMP_HOURS = 24.0
MAX_TEMP_POINTS = 300
# クラウド確定済み(meta.json あり)イベントのCloudFrontキャッシュ秒数。
# 波形は書き込み後不変なので実質半永久(1年)にしてよい。note/checked等の手動編集
# (flag_event.py)を反映させたい時は、待つのではなく手元で
# `aws cloudfront create-invalidation --paths '/event*'` を打つのが前提
# （このTTLの長さでは自然失効を待つ運用は成立しない）。
# 速報のみ(meta.json未生成)はクラウド確定への遷移を取りこぼさないようキャッシュしない
# （CloudFront側のcache policyがCache-Controlヘッダを尊重する前提。terraform/custom_domain.tf参照）。
EVENT_CONFIRMED_CACHE_S = 365 * 24 * 3600
# CORSヘッダは Function URL の cors 設定に任せる（ここで access-control-* を
# 返すと Function URL のぶんと二重になり、ブラウザが弾く）。ここは content-type のみ。
HEADERS = {"content-type": "application/json"}


def _json(code: int, obj, cache_control: str | None = None) -> dict:
    headers = HEADERS if cache_control is None else {**HEADERS, "cache-control": cache_control}
    return {"statusCode": code, "headers": headers, "body": json.dumps(obj, default=_default)}


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
        m = re.search(r"/devices/(\d{1,10})/temp$", path)  # 個別デバイスの温度（より具体的な方を先に）
        if m:
            return _device_temp(int(m.group(1)), q)
        m = re.search(r"/devices/(\d{1,10})$", path)
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
    # 波形は1デバイスぶんに絞る。混ぜると継ぎ目の段差が揺れに見える。
    # 無指定は最若番のデバイス（多点化前のURLがそのまま動くように）。
    device_id = _resolve_device(q.get("device"))
    if device_id is None:
        return _json(200, _waveform_payload(np.empty((0, 3)), end_us, 100.0))
    gal, win_start, fs = store.load_window(s3, BUCKET, end_us, minutes * 60, device_id)
    payload = _waveform_payload(gal, win_start, fs)
    payload["device_id"] = device_id
    return _json(200, payload)


def _resolve_device(raw) -> int | None:
    """?device=<id>。無指定なら最若番。該当が無ければ None。"""
    try:
        if raw is not None:
            return int(raw)
    except (TypeError, ValueError):
        pass
    ids = sorted(int(it["device_id"]) for it in devices.list_devices()
                 if it.get("device_id") is not None)
    return ids[0] if ids else None


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
    # ?device=<id> でデバイス絞り込み。/recent と違い無指定は全デバイス
    # （イベントは混ぜても壊れない。既定で全部見えるほうが「取り逃し」に気付ける）。
    device_id = None
    raw = q.get("device")
    if raw not in (None, "", "all"):
        try:
            device_id = int(raw)
        except (TypeError, ValueError):
            return _json(400, {"error": "bad device"})
    items, total = events.list_page(page, size, show_all=show_all, device_id=device_id)
    # 一覧・詳細で同じ値を出すため、震度は effective_intensity に統一する。
    for it in items:
        eff = events.effective_intensity(it)
        it["max_intensity"] = eff
        it["scale"] = intensity_scale(eff)
    return _json(200, {"events": items, "page": page, "size": size, "total": total,
                       "device_id": device_id})


def _event(q):
    eid = q.get("id", "")
    # event_id は「デバイスID(最低4桁ゼロ埋め、uint32まで)-バケット数値」形式のみ。
    # S3キーに埋め込むため書式を強制する。device_id は :04d 生成のため4桁未満はないが、
    # テスト機のようにuint32最大値(4294967295, 10桁)まで取り得るので上限は10桁で見る。
    if not re.fullmatch(r"\d{4,10}-\d{1,16}", eid):
        return _json(400, {"error": "bad id"})
    # meta.json があれば波形付き（クラウド確定済イベント）。
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=s3util.event_meta_key(eid))
        meta = json.loads(obj["Body"].read())
        meta.setdefault("related_events", [])
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
            meta["manual"] = bool(item.get("manual"))
            # メモは DynamoDB を権威とする（meta.json の値より後の編集を優先）。
            meta["note"] = item.get("note", meta.get("note"))
            # 他デバイスの同一地震イベントへの相互リンク（flag_event.py relate で設定）。
            meta["related_events"] = list(item.get("related_events", []))
    except s3.exceptions.NoSuchKey:
        # 速報のみのイベントは波形コピーが無い。DynamoDBの情報だけ返す。
        item = events.get_event(eid)
        if item is None:
            return _json(404, {"error": "event not found"})
        intensity = float(item.get("max_intensity", 0))
        meta = {
            "event_id": eid,
            "device_id": int(item.get("device_id", 0)),
            "onset_us": int(item.get("onset_us", 0)),
            "last_us": int(item.get("last_us", item.get("onset_us", 0))),
            "max_intensity": intensity,
            "scale": intensity_scale(intensity),
            "peak_gal": float(item.get("peak_gal", 0)),
            "device_prompt": bool(item.get("device_prompt")),
            "cloud_confirmed": bool(item.get("cloud_confirmed")),
            "checked": bool(item.get("checked")),
            "artificial": bool(item.get("artificial")),
            "manual": bool(item.get("manual")),
            "note": item.get("note"),  # ユーザーの自由記述メモ（無ければ null）
            "related_events": list(item.get("related_events", [])),
        }
        # 速報のみはクラウド確定への遷移をキャッシュで取りこぼさないよう明示的に無キャッシュ。
        return _json(200, {"meta": meta, "waveform": _waveform_payload(np.empty((0, 3)), meta["onset_us"], 100.0)},
                     cache_control="max-age=0")
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
    return _json(200, {"meta": meta, "waveform": payload}, cache_control=f"public, max-age={EVENT_CONFIRMED_CACHE_S}")


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
        # watchdogの監視対象外(tools/mute_device.py、lambda/common/watchdog_mute.py)。
        # 立っている間はonlineの真偽に関わらずダッシュボードは「監視停止」を表示する
        # （試験機の再送スパム対策で意図的に黙らせている状態と、本当の欠測を区別する）。
        "watchdog_muted": watchdog_mute.is_muted(item),
        # pull型OTA(docs/ota.md §2)。手元のtools/request_ota.pyが立てる更新許可。
        # 実際のトリガーはバッチ送信レスポンスヘッダ(X-Namz-Ota-Version)経由で
        # デバイスに伝わる。ここはダッシュボード表示用の参照値。
        "pending_ota_version": item.get("pending_ota_version"),
        # リモート再起動要求(docs/remote_restart.md)。一回性の要求で、ingestが
        # 次回バッチ受信時にレスポンスヘッダへ反映した直後に消える。ここに出るのは
        # 「立てたがまだ次のバッチを受信していない」短い窓だけ。
        "pending_restart_requested_at_us": item.get("pending_restart_requested_at_us"),
        # 今このデバイスが動かしている版数(X-Namz-Fw-Version、batch-uplink
        # v1.6.0のextraRequestHeaders経由で毎バッチ送られてくる)。
        # pending_ota_versionと比較すればOTAが実際に着地したか外からも分かる。
        "fw_version": item.get("fw_version", ""),
        # ヘッダのsensor_typeをingestが記録したもの(device_meta.record_sensor_type)。
        # 表示名はwire.SENSOR_TYPE_NAMESが単一の真実。未記録(古いデータ等)はNone。
        "sensor": wire.SENSOR_TYPE_NAMES.get(item.get("sensor_type")),
        # gal単位の物理量として扱ってよいか。detect Lambdaのガードと同じ
        # wire.is_calibrated()が単一の真実（docs/wire_format.md「sensor_typeの帯域」）。
        # dashboardはこれを見て概算震度計算・縦軸のgal表示を非校正センサでは出さない。
        # 未記録(古いデータ・sensor_type未着地)はhasTemp同様「見えないよりまし」で校正扱い。
        "calibrated": (True if item.get("sensor_type") is None
                       else wire.is_calibrated(int(item["sensor_type"]))),
        # 稼働時間(docs/uptime.md)。boot_epoch_usはingestがX-Namz-Uptime-Usヘッダから
        # 逆算・記録したもの(device_meta.record_boot_epoch)。未記録(旧ファーム等)はNone。
        "boot_epoch_us": int(item["boot_epoch_us"]) if item.get("boot_epoch_us") else None,
        "uptime_s": ((now_us - int(item["boot_epoch_us"])) / 1e6)
                   if item.get("boot_epoch_us") else None,
        # 直前の再起動理由(esp_reset_reason()、X-Namz-Reset-Reasonヘッダ経由。
        # docs/log/2026-08-09-uplink-v2.0.0-sentinel-header-arrays.md)。
        # boot_epoch_usと同じタイミングでしか更新されない(device_meta.record_boot_epoch)。
        "reset_reason": item.get("reset_reason"),
        # 姿勢較正(tools/calibrate_orientation.py --write、docs/device_overlay.md §3.b)。
        # tilt_up は raw sensor frame での重力方向の単位ベクトル、azimuth_deg は
        # calibration_ref_device の水平基底に揃えるための回転角(度)。未較正はnull
        # （ダッシュボードの重ね表示モードはここが無い機体を対象外にする）。
        "tilt_up": [float(v) for v in item["tilt_up"]] if item.get("tilt_up") else None,
        "tilt_deg": float(item["tilt_deg"]) if item.get("tilt_deg") is not None else None,
        "azimuth_deg": float(item["azimuth_deg"]) if item.get("azimuth_deg") is not None else None,
        "calibration_ref_device": int(item["calibration_ref_device"])
                                  if item.get("calibration_ref_device") is not None else None,
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
    view = _device_view(item, now_us)
    # ヒープ空き容量(docs/design.md「送信の信頼性」未定事項4)。一覧(_devices)では
    # デバイス数ぶんCloudWatch呼び出しが増えるので詳細ページ限定にしている。
    # 直近データが無い(旧ファーム・未受信)場合は単に出さない。
    try:
        heap = metrics.latest_heap(device_id)
        if heap:
            view.update(heap)
    except Exception as e:  # noqa: BLE001
        print(f"metrics.latest_heap failed: {e!r}")
    # 未送信バックログ(spill=LittleFS退避済み・ram=RAMキュー内)。ヒープと同じ理由で
    # 詳細ページ限定(一覧はデバイス数ぶんCloudWatch呼び出しが増える)。
    try:
        backlog = metrics.latest_backlog(device_id)
        if backlog:
            view.update(backlog)
    except Exception as e:  # noqa: BLE001
        print(f"metrics.latest_backlog failed: {e!r}")
    return _json(200, {"device": view,
                       "offline_after_s": OFFLINE_AFTER_S,
                       "lag_after_s": LAG_AFTER_S})


def _device_temp(device_id: int, q):
    try:
        hours = float(q.get("hours", "3"))
    except (TypeError, ValueError):
        hours = 3.0
    if not math.isfinite(hours):
        hours = 3.0
    hours = max(0.1, min(hours, MAX_TEMP_HOURS))  # 巨大値によるDynamoDB Query暴走を防ぐ
    end_us = int(time.time() * 1e6)
    start_us = int(end_us - hours * 3600 * 1e6)
    items = device_temp.query_range(device_id, start_us, end_us, max_points=MAX_TEMP_POINTS)
    # raw はセンサ生値そのもの、c は換算式が既知（ADXL355）の時だけ付く参考値
    # （校正値ではないので絶対値は当てにならない。ドリフトの相対変化用）。
    points = [{"t": int(it["batch_start_us"]), "raw": int(it["raw"]),
              "c": wire.temp_c_for(int(it["sensor_type"]), int(it["raw"]))} for it in items]
    return _json(200, {"device_id": device_id, "hours": hours, "points": points})


def _pad_to_3ch(gal: np.ndarray) -> np.ndarray:
    """axes<3の非校正センサ(ピエゾ等)向けに、y,z列を0埋めして3列に揃える。

    dashboardはx,y,zの3チャンネル前提で組んである（軸を可変対応させるのは
    別タスク、docs/piezo.md §7参照）。ワイヤ形式・detect Lambdaはaxes可変の
    ままにし、この関数1箇所でdashboard向けの互換性を担保する。
    """
    if gal.shape[1] >= 3:
        return gal[:, :3]
    pad = np.zeros((gal.shape[0], 3 - gal.shape[1]))
    return np.hstack([gal, pad])


def _waveform_payload(gal: np.ndarray, start_us: int, fs: float) -> dict:
    n = gal.shape[0]
    if n == 0:
        return {"mode": "raw", "fs": fs, "start_us": start_us, "n": 0,
                "x": [], "y": [], "z": []}
    gal = _pad_to_3ch(gal)
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
