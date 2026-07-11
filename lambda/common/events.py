"""イベントの DynamoDB 管理。デバイス速報とクラウド確定報を同一イベントに突合する。"""

from __future__ import annotations

import os
from decimal import Decimal

import boto3

# 揺れの発生時刻をこの粒度[us]でバケット化し event_id にする。
# 同じ揺れのデバイス速報とクラウド確定報が同じ event_id に落ちて突合される。
BUCKET_US = 30_000_000  # 30秒

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_EVENTS_TABLE"])
    return _table_cache


def event_id(device_id: int, onset_us: int) -> str:
    bucket = onset_us // BUCKET_US
    return f"{device_id:04d}-{bucket:d}"


def record_device_prompt(device_id, onset_us, intensity, peak_gal):
    """デバイス速報を記録。(event_id, is_new) を返す。"""
    eid = event_id(device_id, onset_us)
    return eid, _upsert(eid, device_id, onset_us, intensity, peak_gal, device_prompt=True)


def record_cloud_detection(device_id, onset_us, intensity, peak_gal, waveform_prefix):
    """クラウド確定報を記録。(event_id, is_new) を返す。"""
    eid = event_id(device_id, onset_us)
    return eid, _upsert(eid, device_id, onset_us, intensity, peak_gal,
                        cloud_confirmed=True, waveform_prefix=waveform_prefix)


def _upsert(eid, device_id, onset_us, intensity, peak_gal,
            device_prompt=False, cloud_confirmed=False, waveform_prefix=None) -> bool:
    """イベントを作成/更新（get→merge→put）。震度・ピークは最大値を保持。新規なら True。

    単一デバイス・30秒バケット運用では並行更新はまず起きないため、
    条件付き更新でなく素直な read-modify-write にしている。
    """
    tbl = _table()
    existing = tbl.get_item(Key={"event_id": eid}).get("Item")
    is_new = existing is None

    item = existing or {
        "event_id": eid,
        "onset_us": onset_us,
        "device_id": device_id,
        "max_intensity": Decimal("0"),
        "peak_gal": Decimal("0"),
        "device_prompt": False,
        "cloud_confirmed": False,
    }
    item["device_id"] = device_id
    item["max_intensity"] = max(Decimal(str(intensity)), Decimal(str(item.get("max_intensity", 0))))
    item["peak_gal"] = max(Decimal(str(peak_gal)), Decimal(str(item.get("peak_gal", 0))))
    if device_prompt:
        item["device_prompt"] = True
    if cloud_confirmed:
        item["cloud_confirmed"] = True
    if waveform_prefix is not None:
        item["waveform_prefix"] = waveform_prefix
    item.setdefault("onset_us", onset_us)

    tbl.put_item(Item=item)
    return is_new


def get_event(eid: str) -> dict | None:
    return _table().get_item(Key={"event_id": eid}).get("Item")


def set_waveform_prefix(eid: str, prefix: str) -> None:
    """波形を events/ へ保存したことを記録（フラグは変えない）。"""
    _table().update_item(
        Key={"event_id": eid},
        UpdateExpression="SET waveform_prefix = :wp",
        ExpressionAttributeValues={":wp": prefix},
    )


def recent_events(limit: int = 50) -> list[dict]:
    """最近のイベントを新しい順で返す（単一デバイス想定の簡易 scan）。"""
    items = _table().scan(Limit=1000).get("Items", [])
    items.sort(key=lambda x: int(x.get("onset_us", 0)), reverse=True)
    return items[:limit]
