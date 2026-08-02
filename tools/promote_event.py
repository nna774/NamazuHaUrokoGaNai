#!/usr/bin/env python3
"""raw/ の一部を手動でイベント化(昇格)して永久保存する手元用CLI。

自動検知(detect)の閾値に満たない弱い揺れや、あとで振り返りたい時間帯を、raw の保持期限
(90日)で消える前に events/ へ退避する。`manual` フラグが立ち、ダッシュボード一覧の
既定にも出る（確定と同格の扱い）。震度は保存区間から計測震度を計算して記録する。

書き込み系なので、api(参照専用)ではなく手元からAWS認証情報で S3/DynamoDB を直接操作する
（flag_event.py と同じ思想）。AWS認証・リージョンは通常の boto3 解決に従う。

    export NAMZ_EVENTS_TABLE=namz-events   # or --table
    # 2026-07-28 16:29 頃の揺れを、前30秒〜後300秒ぶん保存してメモを付ける
    python promote_event.py --onset "2026-07-28 16:29:00" --pre 30 --post 300 \
        --note "熊本の地震。水平2軸でP波到達を確認(detectlab)"

    python promote_event.py --onset "2026-07-28 16:29:00" --dry-run   # 内容だけ表示
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))          # jismo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))  # common

JST = ZoneInfo("Asia/Tokyo")


def parse_jst(s: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=JST).timestamp() * 1e6)
        except ValueError:
            continue
    raise SystemExit(f"--onset をパースできない: {s!r}  例: '2026-07-28 16:29:00'")


def resolve_bucket(explicit: str | None) -> str:
    if explicit:
        return explicit
    for env in ("NAMZ_BUCKET", "NAMZ_RAW_BUCKET", "NAMZ_DATA_BUCKET"):
        if os.environ.get(env):
            return os.environ[env]
    tf = Path(__file__).resolve().parent.parent / "terraform"
    try:
        out = subprocess.run(["terraform", "output", "-raw", "data_bucket"],
                             cwd=tf, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"バケットを解決できない。--bucket か NAMZ_BUCKET を指定しろ ({exc})")


def _batch_start_of(key: str) -> int | None:
    try:
        return int(key.rsplit("/", 1)[-1].split("-", 1)[1].split(".")[0])
    except (IndexError, ValueError):
        return None


def _device_of(key: str) -> int | None:
    try:
        return int(key.rsplit("/", 1)[-1].split("-", 1)[0])
    except (IndexError, ValueError):
        return None


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="raw を手動でイベント化して永久保存する")
    p.add_argument("--onset", required=True, help="揺れの中心/立ち上がり時刻(JST) 例 '2026-07-28 16:29:00'")
    p.add_argument("--pre", type=float, default=30.0, help="onset より前に保存する秒数（既定30）")
    p.add_argument("--post", type=float, default=90.0, help="onset より後に保存する秒数（既定90）")
    p.add_argument("--device", type=int, help="デバイスID（既定: rawのファイル名から推定）")
    p.add_argument("--note", help="イベントに付けるメモ（任意）")
    p.add_argument("--bucket", help="データバケット（既定: NAMZ_BUCKET / terraform）")
    p.add_argument("--table", default=os.environ.get("NAMZ_EVENTS_TABLE"),
                   help="イベントのDynamoDBテーブル名（既定: 環境変数 NAMZ_EVENTS_TABLE）")
    p.add_argument("--dry-run", action="store_true", help="書き込まず内容だけ表示")
    p.add_argument("--yes", "-y", action="store_true", help="確認プロンプトを省略")
    args = p.parse_args(argv)

    if not args.table:
        raise SystemExit("テーブル名が未指定。--table か環境変数 NAMZ_EVENTS_TABLE を設定しろ")
    os.environ["NAMZ_EVENTS_TABLE"] = args.table  # events._table() が参照する
    # boto3 の resource() は AWS_DEFAULT_REGION を見る。AWS_REGION だけの環境でも通す。
    if os.environ.get("AWS_REGION") and not os.environ.get("AWS_DEFAULT_REGION"):
        os.environ["AWS_DEFAULT_REGION"] = os.environ["AWS_REGION"]

    import boto3
    from common import detect_core, events, s3util, store
    from jismo import jma_fft
    from jismo.rounding import intensity_scale

    bucket = resolve_bucket(args.bucket)
    s3 = boto3.client("s3")

    onset_us = parse_jst(args.onset)
    start_us = int(onset_us - args.pre * 1e6)
    end_us = int(onset_us + args.post * 1e6)

    keys = [k for k in store.list_raw_keys_in_range(s3, bucket, start_us, end_us)
            if (bs := _batch_start_of(k)) is not None
            and start_us - 30_000_000 <= bs <= end_us]
    if not keys:
        raise SystemExit("該当する raw バッチが無い。時刻・保持期限(90日)・バケットを確認しろ")
    device_id = args.device if args.device is not None else _device_of(keys[0])
    if device_id is None:
        raise SystemExit("デバイスIDを推定できない。--device で指定しろ")

    gal, win_start, fs = store.load_window(s3, bucket, end_us, (end_us - start_us) / 1e6)
    # 端の扱いを detect Lambda と揃える。ここがずれると手動昇格と自動確定で
    # 同じ波形から違う震度が出る。
    comp = jma_fft.filtered_composite(gal[:, 0], gal[:, 1], gal[:, 2], fs)
    comp = comp[detect_core.core_slice(comp.size, fs)]
    res = jma_fft.intensity_from_composite(comp, fs)
    peak_gal = float(np.max(comp)) if comp.size else 0.0
    eid = events.event_id(device_id, onset_us)

    ot = datetime.fromtimestamp(onset_us / 1e6, JST)
    print(f"# event_id={eid}  device={device_id}")
    print(f"# onset={ot:%Y-%m-%d %H:%M:%S JST}  保存区間 -{args.pre:g}s〜+{args.post:g}s"
          f"  rawバッチ {len(keys)} 個")
    print(f"# 計測震度 I={res.intensity:.1f}（震度{intensity_scale(res.intensity)}）"
          f"  peak={peak_gal:.3f}gal  a0={res.a0:.4f}gal")
    if args.note:
        print(f"# note: {args.note}")

    if args.dry_run:
        print("(dry-run: 何も書き込まない)")
        return 0
    if not args.yes and not _confirm("この内容で events/ へ昇格して保存するか?"):
        raise SystemExit("中止した")

    copied = store.copy_raw_to_event(s3, bucket, eid, start_us, end_us)
    meta = {
        "event_id": eid, "device_id": device_id, "onset_us": onset_us,
        "max_intensity": res.intensity, "scale": intensity_scale(res.intensity),
        "peak_gal": peak_gal, "a0_gal": res.a0, "manual": True,
    }
    if args.note:
        meta["note"] = args.note
    s3.put_object(Bucket=bucket, Key=s3util.event_meta_key(eid),
                  Body=json.dumps(meta, ensure_ascii=False).encode(),
                  ContentType="application/json")
    events.record_manual_event(device_id, onset_us, res.intensity, peak_gal,
                               waveform_prefix=f"{s3util.EVENTS_PREFIX}/{eid}/",
                               note=args.note)
    print(f"昇格完了: {eid}  波形{copied}バッチを events/ へ保存、DynamoDBに記録(manual)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
