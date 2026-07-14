#!/usr/bin/env python3
"""確定済みイベントに人工地震（テスト等）フラグを立てる/降ろす手元用CLI。

ダッシュボードの読み取りAPIは認証なし・参照専用なので、書き込み（フラグ操作）は
手元マシンからAWS認証情報で DynamoDB を直接更新するこのツールで行う。

人工地震フラグを立てたイベントは、イベント一覧の既定では隠れ（「全件」表示にした
ときだけ非該当と同じように薄く出る）、詳細ページで「人工地震（テスト等）」と表示される。
震度などの値や確定/未確定の状態は変えない。

使い方（AWS認証情報とリージョンは通常のboto3の解決に従う）:

    export NAMZ_EVENTS_TABLE=namz-events   # or pass --table

    # 単体で立てる / 降ろす
    python flag_event.py mark   0001-59462454
    python flag_event.py unmark 0001-59462454

    # 指定イベント（含む）より前の同一デバイスのイベントを全部人工地震にする
    #   例: memo「0001-59462454 以前は全部人工地震」
    python flag_event.py mark --before 0001-59462454

    # 確定済みイベントだけを対象にする（未確定は既定フィルタで元々隠れているので
    # わざわざ人工地震にする必要がない、という運用向け）
    python flag_event.py mark --before 0001-59462454 --confirmed-only

    # 現在フラグの立っているイベントを一覧
    python flag_event.py list
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import boto3

EVENT_ID_RE = re.compile(r"\d{4}-\d{1,16}")


def _table(name: str):
    return boto3.resource("dynamodb").Table(name)


def _device_of(eid: str) -> int:
    return int(eid.split("-", 1)[0])


def _scan_all(table) -> list[dict]:
    out: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = table.scan(**kwargs)
        out.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return out


def _set(table, eid: str, value: bool) -> None:
    table.update_item(
        Key={"event_id": eid},
        UpdateExpression="SET artificial = :v",
        ExpressionAttributeValues={":v": bool(value)},
    )


def _targets(table, eid: str, before: bool, confirmed_only: bool = False) -> list[str]:
    """操作対象の event_id 一覧を決める。

    before=False なら指定 eid のみ。before=True なら、指定 eid と同一デバイスで
    onset_us が指定イベント以下（=それ以前に始まった）のものを全部返す。

    confirmed_only=True なら、そのうち確定済み（cloud_confirmed）のものだけに絞る。
    未確定（checked かつ未確定）のイベントは一覧の既定フィルタで元々隠れているため、
    人工地震フラグを立てる意味があるのは実質確定済みだけ、という運用のためのオプション。
    """
    if not before:
        if confirmed_only:
            ref = table.get_item(Key={"event_id": eid}).get("Item")
            if ref is not None and not ref.get("cloud_confirmed"):
                return []
        return [eid]
    ref = table.get_item(Key={"event_id": eid}).get("Item")
    if ref is None:
        sys.exit(f"イベントが見つからない: {eid}")
    device = _device_of(eid)
    cutoff = int(ref.get("onset_us", 0))
    ids = [it["event_id"] for it in _scan_all(table)
           if int(it.get("device_id", _device_of(it["event_id"]))) == device
           and int(it.get("onset_us", 0)) <= cutoff
           and (not confirmed_only or it.get("cloud_confirmed"))]
    return sorted(ids)


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_mark(args, value: bool):
    table = _table(args.table)
    if not EVENT_ID_RE.fullmatch(args.event_id):
        sys.exit(f"event_id の書式が不正: {args.event_id}")
    ids = _targets(table, args.event_id, args.before, args.confirmed_only)
    if not ids:
        print("対象イベントが無い（確定済みに絞った結果 0 件の可能性）")
        return
    verb = "人工地震フラグを立てる" if value else "人工地震フラグを降ろす"
    # --before は複数件を一気に書き換える破壊的操作なので、対象を見せて確認を取る。
    # 単体でも --yes が無ければ確認する（誤ったidへの操作を防ぐ）。
    if not args.yes:
        print(f"以下の {len(ids)} 件に対して{verb}:")
        for eid in ids:
            print(f"  {eid}")
        if not _confirm("実行するか?"):
            sys.exit("中止した")
    for eid in ids:
        _set(table, eid, value)
    print(f"{verb}: {len(ids)} 件 完了")


def cmd_list(args):
    table = _table(args.table)
    items = [it for it in _scan_all(table) if it.get("artificial")]
    items.sort(key=lambda x: int(x.get("onset_us", 0)), reverse=True)
    if not items:
        print("人工地震フラグの立っているイベントはない")
        return
    print(f"人工地震フラグ: {len(items)} 件")
    for it in items:
        print(f"  {it['event_id']}  onset_us={int(it.get('onset_us', 0))}")


def main(argv=None):
    p = argparse.ArgumentParser(description="人工地震フラグの操作")
    default_table = os.environ.get("NAMZ_EVENTS_TABLE")
    p.add_argument("--table", default=default_table,
                   help="イベントのDynamoDBテーブル名（既定: 環境変数 NAMZ_EVENTS_TABLE）")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, help_ in (("mark", "人工地震フラグを立てる"), ("unmark", "人工地震フラグを降ろす")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("event_id")
        s.add_argument("--before", action="store_true",
                       help="指定イベント（含む）より前の同一デバイスのイベントを全部対象にする")
        s.add_argument("--confirmed-only", action="store_true",
                       help="確定済み（cloud_confirmed）イベントだけを対象にする"
                            "（未確定は一覧の既定で元々隠れているため）")
        s.add_argument("--yes", "-y", action="store_true",
                       help="確認プロンプトを省略する")

    sub.add_parser("list", help="人工地震フラグの立っているイベントを一覧")

    args = p.parse_args(argv)
    if not args.table:
        sys.exit("テーブル名が未指定。--table か環境変数 NAMZ_EVENTS_TABLE を設定しろ")

    if args.cmd == "mark":
        cmd_mark(args, True)
    elif args.cmd == "unmark":
        cmd_mark(args, False)
    elif args.cmd == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
