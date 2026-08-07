"""センサ内蔵温度の DynamoDB 記録・照会。

最初はダッシュボードの読み取り側で raw/ のバッチを Range GET して温度トレイラーだけ
取り出す設計にしていたが、コスト・レイテンシの両面で筋が悪いと分かった（S3 GET は
リクエスト数課金でサイズに依らないので、ヘッダ/トレイラーに分けて2回読んでも
リクエスト数はむしろ倍になる。しかも認証なし公開APIなので、閲覧されるたびに
S3アクセスが発生する設計は際限なく課金され得る）。

ingest は受信バッチを既に `wire.parse()` しているので、温度トレイラーの取り出しは
追加のS3アクセスなしで手に入る。書き込み側（ingest、バッチ受信のたび＝低頻度・
量が読み取りに左右されない）で1回記録しておけば、読み取り側は単純な Query で済む。
"""

from __future__ import annotations

import os
import time

import boto3
from boto3.dynamodb.conditions import Key

# raw/ のバッチと違って厳密に揃える理由はない（温度トレンドはドリフトの相対変化を
# 見る用途で、過去に遡って直す運用も想定しない）。90日は raw_retention_days の既定と
# 同じ桁感というだけの目安。
TTL_DAYS = 90

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICE_TEMP_TABLE"])
    return _table_cache


def record(device_id: int, batch_start_us: int, raw: int, sensor_type: int) -> None:
    """1バッチぶんの温度を記録する。

    device_id + batch_start_us が同じ書き込みは上書き（バッチの二重送信と同じ理由で冪等）。
    """
    _table().put_item(Item={
        "device_id": device_id,
        "batch_start_us": batch_start_us,
        "raw": raw,
        "sensor_type": sensor_type,
        "ttl": int(time.time() + TTL_DAYS * 86400),
    })


def query_range(device_id: int, start_us: int, end_us: int,
                max_points: int = 300) -> list[dict]:
    """[start_us, end_us] の温度を時刻順で返す。多ければ均等に間引く。

    15〜30秒に1点なので、24時間でも数千件程度。ページングで全件拾ってから
    間引く（Query自体の回数は窓の長さに依らずほぼ数回で済む）。
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
