"""デバイスの静的な属性（センサ種別など）を namazu-devices 台帳に記録する。

batch-uplink 側の`devices.record_batch()`は生存台帳の汎用項目（受信時刻・累計数・
版数）だけを扱う共有ライブラリの関数なので、Namazu固有の属性はここで別に
`update_item`する（`ota_watch.py`と同じ考え方。部分更新なので他フィールドは壊れない）。
"""

from __future__ import annotations

import os

import boto3

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])
    return _table_cache


def record_sensor_type(device_id: int, sensor_type: int) -> None:
    """このバッチのヘッダから読んだセンサ種別を記録する（毎バッチ呼んでよい）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET sensor_type = :s",
        ExpressionAttributeValues={":s": sensor_type},
    )
