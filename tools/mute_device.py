#!/usr/bin/env python3
"""デバイスをwatchdogの欠測監視から外す/戻す手元用CLI。

退役デバイスや、ハード試験のたびに繋いでは黙る試験機（`tools/devices.json`の
fake-sensor機など）向け。mute中はwatchdogが完全に無視するので再送スパムが
止まる。ingestが実際にバッチを受信すると自動でunmuteされる
（`lambda/common/watchdog_mute.py`参照）ので、次に試験を始める時に手動で
unmuteし直す必要は無い——試験が終わって黙ったタイミングで、このCLIで
再度muteするだけでよい。

使い方（AWS認証情報とリージョンは通常のboto3の解決に従う）:

    export NAMZ_DEVICES_TABLE=namz-devices   # or pass --table

    python mute_device.py mute 4294967295          # 監視対象外にする
    python mute_device.py mute 4294967295 --yes    # 確認プロンプトを省略
    python mute_device.py unmute 4294967295        # 監視対象に戻す（手動）
    python mute_device.py list                     # 現在muteされているデバイスを一覧
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import awsenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))
from batch_uplink import devices  # noqa: E402
from common import watchdog_mute  # noqa: E402


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_mute(args):
    item = devices.get_device(args.device_id)
    if item is None:
        sys.exit(f"デバイスが見つからない（一度も送信していない?）: device {args.device_id}")
    if not args.yes and not _confirm(f"device {args.device_id} を監視対象外にするか?"):
        sys.exit("中止した")
    watchdog_mute.mute(args.device_id)
    print(f"監視対象外にした: device {args.device_id}"
          "（次にバッチを送信すると自動で監視対象に戻る）")


def cmd_unmute(args):
    watchdog_mute.clear_mute(args.device_id)
    print(f"監視対象に戻した: device {args.device_id}")


def cmd_list(_args):
    items = [it for it in devices.list_devices() if watchdog_mute.is_muted(it)]
    if not items:
        print("mute されているデバイスはない")
        return
    print(f"mute中: {len(items)} 件")
    for it in items:
        did = int(it.get("device_id", 0))
        print(f"  device {did}")


def main(argv=None):
    p = argparse.ArgumentParser(description="デバイスのwatchdog監視対象外(mute)の操作")
    default_table = os.environ.get("NAMZ_DEVICES_TABLE")
    p.add_argument("--table", default=default_table,
                   help="デバイスのDynamoDBテーブル名（既定: 環境変数 NAMZ_DEVICES_TABLE）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("mute", help="監視対象外にする")
    s.add_argument("device_id", type=int, help="対象デバイスID")
    s.add_argument("--yes", "-y", action="store_true", help="確認プロンプトを省略する")

    s = sub.add_parser("unmute", help="監視対象に戻す")
    s.add_argument("device_id", type=int, help="対象デバイスID")

    sub.add_parser("list", help="mute中のデバイスを一覧")

    args = p.parse_args(argv)
    if not args.table:
        sys.exit("テーブル名が未指定。--table か環境変数 NAMZ_DEVICES_TABLE を設定しろ")
    # devices.py / watchdog_mute.py の _table() は環境変数からしかテーブル名を
    # 取らないので、--table 指定時はここで環境変数に反映してから呼ぶ。
    os.environ["NAMZ_DEVICES_TABLE"] = args.table
    awsenv.ensure_region()

    if args.cmd == "mute":
        cmd_mute(args)
    elif args.cmd == "unmute":
        cmd_unmute(args)
    elif args.cmd == "list":
        cmd_list(args)


if __name__ == "__main__":
    main()
