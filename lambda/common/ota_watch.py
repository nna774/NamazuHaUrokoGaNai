"""pull型OTAの停滞検知・達成検知（docs/ota.md §2）。

`pending_ota_version` は一度伝えたら消す一回性の値ではなく、デバイスが実際に
そのバージョンで起動するまでサーバが持ち続ける「あるべき状態」。そのため、
サーバ側からは「デバイスが取得に成功したか」を直接は観測できない
——というのが元々の前提だったが、firmwareが毎バッチ`X-Namz-Fw-Version`で
現在版数を送るようになったことで、「達成したか」はingestが受信するバッチ
から分かるようになった（`fw_version`と`pending_ota_version`の一致）。
達成したら`reached_target()`でこの一致を判定し、ingest側で
`clear_ota_target()`を呼んでサーバ側の状態を解放する
（さもないと`pending_ota_version`が達成後も残り続け、時間経過だけを見る
`evaluate_ota_stuck()`が成功後も「停滞」を誤検知する）。

それでも「達成前に何が起きているか」（証明書検証失敗か・ネットワーク不調か等）
はデバイスのシリアルログでしか分からないので、停滞検知（時間経過ベース）は
引き続き必要。代わりに「要求してから長時間経っても解消しない」ことを
watchdog Lambda が外側から検知してSlack通知する。原因は問わない（原因は
デバイスのシリアルログでしか分からないが、「何かがおかしい」こと自体は
気づけるようにする）。

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


def reached_target(item: dict) -> bool:
    """このバッチの`fw_version`が`pending_ota_version`に追いついたか。"""
    pending = item.get("pending_ota_version")
    return bool(pending) and item.get("fw_version") == pending


def clear_ota_target(device_id: int, matched_version: str) -> None:
    """達成済みの`pending_ota_version`をサーバ側から解放する。

    要求してからここまでの間に別バージョンが新たに要求されているかも
    しれないので、読んだ時の値のまま変わっていない場合だけ消す
    （condition不成立はレースで新しい要求が割り込んだだけなので無視してよい）。
    """
    try:
        _table().update_item(
            Key={"device_id": device_id},
            UpdateExpression="REMOVE pending_ota_version, pending_ota_requested_at_us, "
                              "ota_stuck_notified_at_us",
            ConditionExpression="pending_ota_version = :v",
            ExpressionAttributeValues={":v": matched_version},
        )
    except _table().meta.client.exceptions.ConditionalCheckFailedException:
        pass
