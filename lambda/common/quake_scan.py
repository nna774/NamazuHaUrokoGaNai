"""地震候補スキャン(docs/auto_judge.md)の状態管理。

自動化するのは「気象庁の地震一覧から候補に気付いてSlackへ知らせる」ところまでで、
解析・判定・保存はしない。そのため持つ状態は2種類だけ:

1. 通知済みJMA `eid` の集合（二重通知の防止。重複排除の窓を実行間隔より広めに
   取る設計なので、同じ候補が複数回の実行にまたがって出てくる）。
2. 最後に成功実行した時刻（watchdog Lambdaの停滞検知が読む）。

どちらも小さな1テーブル(namazu-quake-scan、hash_key="id")に持たせる——(1)は
`id`=eidの行、(2)は固定キー`_state`の行。ota_watch.pyと同じ「純粋関数(判定)＋
薄いDynamoDBアクセス」の分離。
"""

from __future__ import annotations

import os
import time

import boto3

_table_cache = None

STATE_KEY = "_state"

# 通知済みeidの保持期間。list.jsonは直近~1ヶ月分しかロールしないので、
# それより十分長く持てば同じeidが再度候補に上がって重複通知されることはない。
NOTIFIED_TTL_S = 60 * 24 * 3600  # 60日


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_QUAKE_SCAN_TABLE"])
    return _table_cache


def filter_new(eids: list[str], notified: set[str]) -> list[str]:
    """まだ通知していないeidだけを順序維持で返す（DynamoDB抜きでテストできる）。"""
    return [e for e in eids if e not in notified]


def get_notified_eids(eids: list[str]) -> set[str]:
    """候補のeid群のうち、既に通知済みのものの集合を返す。

    1日あたりの候補数は多くてもせいぜい数件〜数十件で、DynamoDBの
    batch_get_item の上限(100件)に収まる前提（超える日があれば分割が要る）。
    """
    if not eids:
        return set()
    table_name = os.environ["NAMZ_QUAKE_SCAN_TABLE"]
    resp = boto3.resource("dynamodb").batch_get_item(
        RequestItems={table_name: {"Keys": [{"id": e} for e in eids]}}
    )
    return {item["id"] for item in resp["Responses"].get(table_name, [])}


def mark_notified(eids: list[str], at_us: int) -> None:
    """通知したeidを記録する（TTL付き）。"""
    ttl = int(time.time()) + NOTIFIED_TTL_S
    with _table().batch_writer() as batch:
        for e in eids:
            batch.put_item(Item={"id": e, "notified_at_us": at_us, "ttl": ttl})


def mark_success(at_us: int) -> None:
    """成功実行を記録する。以前の停滞通知マーカーが残っていれば併せて消す
    （次に本当に停滞した時、watchdogが"stuck"として素直に初回通知できるように）。"""
    _table().update_item(
        Key={"id": STATE_KEY},
        UpdateExpression="SET last_success_at_us = :t REMOVE stuck_notified_at_us",
        ExpressionAttributeValues={":t": at_us},
    )


def get_state() -> dict:
    resp = _table().get_item(Key={"id": STATE_KEY})
    return resp.get("Item", {})


def evaluate_stuck(state: dict, now_us: int, stuck_after_us: int,
                    renotify_after_us: int) -> str | None:
    """通知が要るなら "stuck"（初回）/"stuck_again"（再送）、不要ならNone。

    ota_watch.evaluate_ota_stuck()と同じ形の純粋関数（DynamoDB抜きでテストできる）。
    last_success_at_usが無い（一度も成功実行していない）場合は判定しない——
    デプロイ直後、初回実行がまだ走っていないだけの状態を誤検知しないため。
    """
    last_success = state.get("last_success_at_us")
    if not last_success:
        return None
    if now_us - int(last_success) < stuck_after_us:
        return None
    notified_at = int(state.get("stuck_notified_at_us", 0) or 0)
    if not notified_at:
        return "stuck"
    if now_us - notified_at >= renotify_after_us:
        return "stuck_again"
    return None


def mark_stuck_notified(at_us: int) -> None:
    _table().update_item(
        Key={"id": STATE_KEY},
        UpdateExpression="SET stuck_notified_at_us = :t",
        ExpressionAttributeValues={":t": at_us},
    )
