#!/usr/bin/env python3
"""デバイスにpull型OTAの更新を許可する/取り消す手元用CLI（docs/ota.md §7）。

デバイスは定期的にapi Lambda(/devices/<id>)へ問い合わせ、pending_ota_versionが
自分のビルドバージョン(NAMZ_FW_VERSION)と違えば安全停止シーケンスを経てから
esp_https_otaで取得・書き込みする。リモート再起動要求(request_restart.py)と
違い、値は一度伝えたら消す一回性のものではない——ターゲットは「あるべき状態」
なので、デバイスが実際にそのバージョンで起動するまで照合し続けてよい
（取得・書き込み失敗時の自然なリトライにもなる）。

使い方（AWS認証情報とリージョンは通常のboto3の解決に従う）:

    export NAMZ_DEVICES_TABLE=namz-devices   # or pass --table

    python request_ota.py request 1 a1b2c3d        # device 1 に a1b2c3d への更新を許可
    python request_ota.py request 1 a1b2c3d --yes  # 確認プロンプトを省略
    python request_ota.py cancel 1                 # 許可を取り消す
    python request_ota.py list                     # 現在許可が立っているデバイスを一覧
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import awsenv  # noqa: E402

import boto3  # noqa: E402
from batch_uplink import devices  # noqa: E402

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_DEVICES_TABLE"])
    return _table_cache


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_request(args):
    item = devices.get_device(args.device_id)
    if item is None:
        sys.exit(f"デバイスが見つからない（一度も送信していない?）: device {args.device_id}")
    if not args.yes and not _confirm(
            f"device {args.device_id} に version={args.version} への更新を許可するか?"):
        sys.exit("中止した")
    _table().update_item(
        Key={"device_id": args.device_id},
        UpdateExpression="SET pending_ota_version = :v, pending_ota_requested_at_us = :t "
                          "REMOVE ota_stuck_notified_at_us",
        ExpressionAttributeValues={":v": args.version, ":t": int(time.time() * 1e6)},
    )
    print(f"更新を許可した: device {args.device_id} -> version={args.version}"
          "（次回のデバイスからの問い合わせで反映される）")


def cmd_cancel(args):
    _table().update_item(
        Key={"device_id": args.device_id},
        UpdateExpression="REMOVE pending_ota_version, pending_ota_requested_at_us, "
                          "ota_stuck_notified_at_us",
    )
    print(f"更新許可を取り消した: device {args.device_id}")


def cmd_list(_args):
    items = [it for it in devices.list_devices() if it.get("pending_ota_version")]
    if not items:
        print("更新許可の立っているデバイスはない")
        return
    print(f"更新許可: {len(items)} 件")
    for it in items:
        did = int(it.get("device_id", 0))
        requested_at = it.get("pending_ota_requested_at_us")
        age_s = int(time.time() - int(requested_at) / 1e6) if requested_at else None
        suffix = f"（{age_s}秒前に要求）" if age_s is not None else ""
        print(f"  device {did}  pending_ota_version={it['pending_ota_version']}{suffix}")


def main(argv=None):
    p = argparse.ArgumentParser(description="デバイスへのpull型OTA更新許可の操作")
    default_table = os.environ.get("NAMZ_DEVICES_TABLE")
    p.add_argument("--table", default=default_table,
                   help="デバイスのDynamoDBテーブル名（既定: 環境変数 NAMZ_DEVICES_TABLE）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("request", help="更新を許可する")
    s.add_argument("device_id", type=int, help="対象デバイスID")
    s.add_argument("version", help="許可するバージョン（NAMZ_FW_VERSIONと一致する短縮hash）")
    s.add_argument("--yes", "-y", action="store_true", help="確認プロンプトを省略する")

    s = sub.add_parser("cancel", help="更新許可を取り消す")
    s.add_argument("device_id", type=int, help="対象デバイスID")

    sub.add_parser("list", help="更新許可の立っているデバイスを一覧")

    args = p.parse_args(argv)
    if not args.table:
        sys.exit("テーブル名が未指定。--table か環境変数 NAMZ_DEVICES_TABLE を設定しろ")
    os.environ["NAMZ_DEVICES_TABLE"] = args.table
    awsenv.ensure_region()

    if args.cmd == "request":
        cmd_request(args)
    elif args.cmd == "cancel":
        cmd_cancel(args)
    elif args.cmd == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
