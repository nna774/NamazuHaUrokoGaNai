"""CloudWatchへNamazu固有のカスタムメトリクスを送る薄いラッパー。

`namazu-devices`(device_meta.py)は「現在値」の台帳で、上書きなので障害調査に
要る推移は追えない。時系列が要る値はここ経由でCloudWatchへ逃がす
（docs/design.md「送信の信頼性」未定事項4）。
"""

from __future__ import annotations

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
