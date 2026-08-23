"""デバイスの静的な属性（センサ種別など）を namazu-devices 台帳に記録する。

batch-uplink 側の`devices.record_batch()`は生存台帳の汎用項目（受信時刻・累計数・
版数）だけを扱う共有ライブラリの関数なので、Namazu固有の属性はここで別に
`update_item`する（`ota_watch.py`と同じ考え方。部分更新なので他フィールドは壊れない）。
"""

from __future__ import annotations

import os

import boto3

_table_cache = None

# 再起動検知の閾値（TimeSyncのドリフト許容。docs/uptime.md §3・§6）。
# boot_epoch_us の逆算値がこれを超えてズレていたら「再起動があった」とみなす。
BOOT_EPOCH_DRIFT_THRESHOLD_US = 120_000_000  # ±2分


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


def record_sensor_type_and_clear_mute(device_id: int, sensor_type: int) -> None:
    """record_sensor_type()とwatchdog_mute.clear_mute()を1回のupdate_itemに統合する。

    ingestの毎バッチ経路専用（docs/log/2026-08-23-s3-dynamodb-cost-cross-account-investigation.md）。
    どちらも同一device_idの同一項目への書き込みなので、別々に呼ぶとDynamoDBの
    WCUが呼び出し回数分よけいにかかる。REMOVEは対象属性が無くても失敗しないので、
    mute中でなくても無条件で混ぜてよい（watchdog_mute.clear_mute()と同じ前提）。
    手元CLI(tools/mute_device.py)の単体unmuteはこの関数を使わず
    watchdog_mute.clear_mute()を直接呼ぶ（sensor_typeを知らないため）。
    """
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET sensor_type = :s REMOVE watchdog_muted",
        ExpressionAttributeValues={":s": sensor_type},
    )


def should_update_boot_epoch(prev_boot_epoch_us, new_boot_epoch_us: int) -> bool:
    """ブートepochを書き換えるべきか(=再起動を検知したか)を判定する（副作用なし）。

    未記録(prev=None、初回受信)なら無条件で書く。既に記録済みなら
    BOOT_EPOCH_DRIFT_THRESHOLD_USを超えてズレた時だけ「再起動があった」とみなす
    （devices.evaluate()と同じ、状態遷移を副作用から切り離すための設計）。
    """
    if prev_boot_epoch_us is None:
        return True
    return abs(new_boot_epoch_us - int(prev_boot_epoch_us)) > BOOT_EPOCH_DRIFT_THRESHOLD_US


def record_boot_epoch(device_id: int, boot_epoch_us: int, reset_reason: str = "") -> None:
    """起動時刻(boot_epoch_us = batch_start_us - uptime_us)を記録する。

    呼び出し側(ingest)がBOOT_EPOCH_DRIFT_THRESHOLD_USを超えたズレ（＝再起動）を
    検知した時だけ呼ぶ想定。この差分検知自体が再起動検知になる（docs/uptime.md §3）。

    reset_reasonはX-Namz-Reset-Reasonヘッダ(esp_reset_reason())の値。再起動を
    検知した瞬間にしか意味を持たない値なので、同じUpdateItemに相乗りさせる
    （追加の書き込みは発生しない）。空文字なら書かない（旧ファーム等、ヘッダが
    無い場合に前回値を消さないため）。
    """
    if reset_reason:
        _table().update_item(
            Key={"device_id": device_id},
            UpdateExpression="SET boot_epoch_us = :b, reset_reason = :r",
            ExpressionAttributeValues={":b": int(boot_epoch_us), ":r": reset_reason},
        )
    else:
        _table().update_item(
            Key={"device_id": device_id},
            UpdateExpression="SET boot_epoch_us = :b",
            ExpressionAttributeValues={":b": int(boot_epoch_us)},
        )
