"""pull型OTAの停滞検知（docs/ota.md §7）。

`pending_ota_version` は一度伝えたら消す一回性の値ではなく、デバイスが実際に
そのバージョンで起動するまでサーバが持ち続ける「あるべき状態」。そのため、
サーバ側からは「デバイスが取得に成功したか」を直接は観測できない
（NVSの秘密情報と同じ理由でデバイスは自分の状態をpushしてこない）。

代わりに「要求してから長時間経っても解消しない」ことを watchdog Lambda が
外側から検知してSlack通知する。証明書検証の失敗・ネットワーク不調・配布物の
取り違えなど原因は問わない（原因はデバイスのシリアルログでしか分からないが、
「何かがおかしい」こと自体は気づけるようにする）。

書き込み関数はNamazu固有の概念なのでbatch-uplink(共有ライブラリ)には置かず、
このリポジトリのlambda/common側に持つ。
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


def evaluate_ota_stuck(item: dict, now_us: int, stuck_after_us: int,
                       renotify_after_us: int) -> str | None:
    """通知が要るなら "stuck"（初回）/"stuck_again"（再送）、不要なら None。

    DynamoDB抜きでテストできるよう、判定はこの純粋関数に集約する
    （devices.evaluate()と同じ考え方）。
    """
    pending = item.get("pending_ota_version")
    requested_at = int(item.get("pending_ota_requested_at_us", 0) or 0)
    if not pending or not requested_at:
        return None
    if now_us - requested_at < stuck_after_us:
        return None
    notified_at = int(item.get("ota_stuck_notified_at_us", 0) or 0)
    if not notified_at:
        return "stuck"
    if now_us - notified_at >= renotify_after_us:
        return "stuck_again"
    return None


def mark_ota_stuck_notified(device_id: int, at_us: int) -> None:
    _table().update_item(
        Key={"device_id": device_id},
        UpdateExpression="SET ota_stuck_notified_at_us = :t",
        ExpressionAttributeValues={":t": at_us},
    )
