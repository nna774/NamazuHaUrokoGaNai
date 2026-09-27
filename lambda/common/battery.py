"""UPSバッテリー電圧の DynamoDB 記録・照会。device_temp.py と同型の設計。

当初CloudWatchカスタムメトリクスとして実装したが撤回した。CloudWatchは
「メトリクス種別×次元」ごとに送信頻度と無関係な固定費がかかるため、種別を1つ
増やすたびに恒久的な月額が積み上がる。device_temp.py が同じ「低頻度・書き込み側で
頻度が天井打ちする時系列」向けに確立している設計（オンデマンドDynamoDB、書き込みは
バッチ受信のたび、読み取りは公開APIでもDynamoDB Queryのみでコストが閲覧回数に
比例しない）をそのまま転用する方が安い。間引き（旧実装は5分間隔でCloudWatchへ
送っていた）も不要になる——書き込み従量課金はこの程度の頻度なら無視できる。
"""

from __future__ import annotations

import os
import time

import boto3
from boto3.dynamodb.conditions import Key

# device_temp.py と同じ理由（過去に遡って直す運用を想定しない）で同じ90日を使う。
TTL_DAYS = 90

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICE_BATTERY_TABLE"])
    return _table_cache


def record(device_id: int, batch_start_us: int, battery_mv: int) -> None:
    """1バッチぶんの電池電圧[mV]を記録する。

    device_id + batch_start_us が同じ書き込みは上書き（バッチの二重送信と同じ理由で冪等）。
    """
    _table().put_item(Item={
        "device_id": device_id,
        "batch_start_us": batch_start_us,
        "battery_mv": battery_mv,
        "ttl": int(time.time() + TTL_DAYS * 86400),
    })


def query_range(device_id: int, start_us: int, end_us: int,
                max_points: int = 300) -> list[dict]:
    """[start_us, end_us] の電池電圧を時刻順で返す。多ければ均等に間引く。

    device_temp.query_range() と同じ実装（Query自体の回数は窓の長さに依らずほぼ数回で済む）。
    """
    tbl = _table()
    items: list[dict] = []
    kwargs: dict = {
        "KeyConditionExpression":
            Key("device_id").eq(device_id) & Key("batch_start_us").between(start_us, end_us),
    }
    while True:
        resp = tbl.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    items.sort(key=lambda it: int(it["batch_start_us"]))
    if len(items) > max_points:
        stride = -(-len(items) // max_points)  # ceil division
        items = items[::stride]
    return items
