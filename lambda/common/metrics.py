"""CloudWatchへNamazu固有のカスタムメトリクスを送る薄いラッパー。

`namazu-devices`(device_meta.py)は「現在値」の台帳で、上書きなので障害調査に
要る推移は追えない。時系列が要る値はここ経由でCloudWatchへ逃がす
（docs/design.md「送信の信頼性」未定事項4）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3

_client_cache = None

NAMESPACE = "Namazu"


def _client():
    global _client_cache
    if _client_cache is None:
        _client_cache = boto3.client("cloudwatch")
    return _client_cache


def record_heap(device_id: int, heap_free: int, heap_maxblock: int) -> None:
    """毎バッチのヒープ空き容量をカスタムメトリクスとして送る（呼んでよい頻度は毎バッチ）。

    maxblockは空き合計より断片化の兆候を直接示す（TLSハンドシェイクは大きな
    連続ブロックを要求するため、バックフィル中の連続POSTでここが先に痩せる）。
    """
    dims = [{"Name": "DeviceId", "Value": str(device_id)}]
    _client().put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[
            {"MetricName": "HeapFreeBytes", "Dimensions": dims,
             "Value": float(heap_free), "Unit": "Bytes"},
            {"MetricName": "HeapMaxAllocBytes", "Dimensions": dims,
             "Value": float(heap_maxblock), "Unit": "Bytes"},
        ],
    )


def record_backlog(device_id: int, spill_count: int, ram_queued: int) -> None:
    """毎バッチの未送信バックログ件数(spill=LittleFS退避済み・ram=RAMキュー内)を送る。

    2つに分けて送るのはheap free/maxblockと同じ理由——spillが多いのは電源断
    からの復旧中、ramが多いのは今まさに送信が詰まっている、で原因が違うため、
    合算すると見分けが付かなくなる。
    """
    dims = [{"Name": "DeviceId", "Value": str(device_id)}]
    _client().put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[
            {"MetricName": "SpillCount", "Dimensions": dims,
             "Value": float(spill_count), "Unit": "Count"},
            {"MetricName": "RamQueued", "Dimensions": dims,
             "Value": float(ram_queued), "Unit": "Count"},
        ],
    )


def _latest_point(metric_name: str, device_id: int, minutes: int = 10):
    """直近`minutes`分の1分解像度データポイントのうち一番新しいものを返す（無ければNone）。"""
    now = datetime.now(timezone.utc)
    resp = _client().get_metric_statistics(
        Namespace=NAMESPACE,
        MetricName=metric_name,
        Dimensions=[{"Name": "DeviceId", "Value": str(device_id)}],
        StartTime=now - timedelta(minutes=minutes),
        EndTime=now,
        Period=60,
        Statistics=["Average"],
    )
    points = resp.get("Datapoints", [])
    if not points:
        return None
    return max(points, key=lambda p: p["Timestamp"])


def latest_heap(device_id: int) -> dict | None:
    """デバイス詳細ページの「軽く見る」用途で、直近1点だけ返す。

    トレンド全体（何分前から何が起きていたか）はCloudWatchコンソール側に
    任せる想定で、ここでは「今どうなっているか」の一瞥だけを提供する。
    """
    free = _latest_point("HeapFreeBytes", device_id)
    maxblock = _latest_point("HeapMaxAllocBytes", device_id)
    if free is None or maxblock is None:
        return None
    return {
        "heap_free_bytes": round(free["Average"]),
        "heap_maxblock_bytes": round(maxblock["Average"]),
        "heap_measured_at_us": int(free["Timestamp"].timestamp() * 1e6),
    }


def latest_backlog(device_id: int) -> dict | None:
    """デバイス詳細ページの「軽く見る」用途で、未送信バックログの直近1点だけ返す。"""
    spill = _latest_point("SpillCount", device_id)
    ram = _latest_point("RamQueued", device_id)
    if spill is None or ram is None:
        return None
    return {
        "spill_count": round(spill["Average"]),
        "ram_queued": round(ram["Average"]),
        "backlog_measured_at_us": int(spill["Timestamp"].timestamp() * 1e6),
    }
