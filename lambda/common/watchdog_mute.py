"""退役・一時停止したデバイスをwatchdogの欠測監視から外す「mute」。

`docs/STATUS.md`の残タスク（退役デバイスの扱い）への対応。恒久的な退役だけでなく、
`tools/devices.json`のテスト機（fake-sensor基板など、ハード試験のたびに繋いでは
また黙る機体）にも使う想定: mute中はwatchdogが完全に無視するが、ingestが実際に
バッチを受信した瞬間に自動でunmuteされる。つまり「試験を始めて送信が来た時点で
監視が復帰し、試験中に落ちれば通常通り通知が来る。試験が終わって黙ったら1回だけ
欠測通知が来るので、そこで手元CLI(`tools/mute_device.py`)で再度muteする」という
運用になる。

Namazu固有の概念なのでbatch-uplink(共有ライブラリ)には置かず、`ota_watch.py`や
`device_meta.py`と同じ考え方でこのリポジトリのlambda/common側に持つ。
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


def is_muted(item: dict) -> bool:
    """watchdogがこのデバイスを無視すべきか（副作用なし・テスト用）。"""
    return bool(item.get("watchdog_muted"))


def mute(device_id: int) -> None:
    """監視対象外にする（手元CLI専用）。"""
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET watchdog_muted = :t",
        ExpressionAttributeValues={":t": True},
    )


def clear_mute_fragment() -> tuple[str, dict]:
    """clear_mute()と同じ書き込み内容を、実行せず断片として返す。

    ingestの毎バッチ経路では他の関心事(device_meta.sensor_type_fragment()等)と
    まとめて1回のupdate_itemに合流させたいので、`dynamo_update.UpdateItemBuilder`
    に渡す用途で公開する（docs/log/2026-08-23-ingest-devices-table-update-item-merge.md）。
    """
    return "REMOVE watchdog_muted", {}


def clear_mute(device_id: int) -> None:
    """監視対象に戻す（単体呼び出し用）。ingest以外の呼び出し元
    （手元CLI等、他の関心事と合流させる必要が無い場合）はこちらを直接使う。
    mute中でなくても無条件で呼んでよい（REMOVEは対象属性が無くても失敗しない）。"""
    expr, _ = clear_mute_fragment()
    _table().update_item(Key={"device_id": device_id}, UpdateExpression=expr)
