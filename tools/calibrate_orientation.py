#!/usr/bin/env python3
"""複数機を人工加振(机を叩く等)して相対的な傾き・方位を較正する手元用CLI。

原理は docs/device_overlay.md の「3.b 方位を較正する」:
- 傾き(2自由度)は静穏区間の重力DCから決まる。
- 方位(水平面内1自由度)は重力だけでは決まらないので、方向の分かっている振動が要る。
  複数機を同時に人工加振し、タップ直後の水平粒子運動の主軸が一致するように片方を
  回してやれば、その回転角が相対方位差になる。

前提: 各イベントが `namazu-events` に記録済み(device_prompt/cloud_confirmed どちらでも
可)で、`events/<id>/` に波形が永久保存されていること(detect Lambdaが確定時に自動で
やる。artificial フラグは別途 flag_event.py で立てておくとイベント一覧が汚れない)。

    export NAMZ_EVENTS_TABLE=namazu-events
    export NAMZ_DEVICES_TABLE=namazu-devices

    # 1号機を基準に2号機の傾き・相対方位を見る(書き込みなし)
    python calibrate_orientation.py 0001-59541742 0002-59541742

    # namazu-devices に書き込む(確認あり。-y で省略)
    python calibrate_orientation.py 0001-59541742 0002-59541742 --write

3台以上を同時に叩いた場合はイベントIDを並べるだけでよい(全機が --ref に揃う)。
データが増えて叩き直したら、同じコマンドを新しいイベントIDで再実行すれば上書きできる
(較正値は毎回全体を上書きする。差分更新ではない)。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))          # detectlab, awsenv
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))  # common

import awsenv  # noqa: E402
import detectlab  # noqa: E402  resolve_bucket/load_s3_event を再利用

# 静穏区間: onset の QUIET_MARGIN_S 秒前までの QUIET_WINDOW_S 秒分を重力DCの推定に使う。
# detect Lambda の PRE_SECONDS=30 が保存されている前提でこれより短く取る。
QUIET_WINDOW_S = 25.0
QUIET_MARGIN_S = 0.5
# タップ直後の水平粒子運動を見る窓。狭いほど反響(部屋・ブロックの共振)の汚染が減る。
# 実測(2026-08-09、机を叩くテスト)ではこの窓で回転コヒーレンス0.98が出た。
TAP_WINDOW_S = (-0.2, 0.5)
LAG_RANGE_MS = 150
LAG_STEP_MS = 1
# コヒーレンス(0..1、1が完全な剛体一致)がこれ未満なら警告する。
COHERENCE_WARN_THRESHOLD = 0.7


def resolve_table(explicit: str | None, env: str, tf_output: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get(env):
        return os.environ[env]
    if not tf_output:
        raise SystemExit(f"{env} を解決できない。--table 系オプションか環境変数で指定しろ")
    import subprocess
    tf = Path(__file__).resolve().parent.parent / "terraform"
    try:
        out = subprocess.run(["terraform", "output", "-raw", tf_output],
                             cwd=tf, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{env} を解決できない。--table 系オプションか環境変数で指定しろ ({exc})")


def device_of(eid: str) -> int:
    try:
        return int(eid.split("-", 1)[0])
    except (IndexError, ValueError):
        raise SystemExit(f"イベントIDの形式が変: {eid!r}（例: 0001-59541742）")


def frame_from_up(up: np.ndarray) -> np.ndarray:
    """up(重力方向の単位ベクトル、raw sensor frame)から (h1,h2,UD) 基底を作る。

    h1,h2 は「upに直交する適当な水平基底」であって物理的な東西南北ではない。
    ref=[1,0,0](raw frameのX軸)をupへ直交射影して作るが、これはraw frameに固有の
    決定的な手続きなので、同じ機体・同じ据え付けなら常に同じ基底になる
    (=較正のやり直しでも azimuth_deg の意味がぶれない)。
    """
    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, up)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    h1 = ref - np.dot(ref, up) * up
    h1 /= np.linalg.norm(h1)
    h2 = np.cross(up, h1)
    return np.stack([h1, h2, up], axis=0)


class DeviceCal:
    def __init__(self, eid: str, device_id: int, onset_us: int, gal: np.ndarray,
                start_us: int, fs: float):
        self.eid = eid
        self.device_id = device_id
        idx_onset = int(round((onset_us - start_us) / 1e6 * fs))
        quiet_hi = idx_onset - int(round(QUIET_MARGIN_S * fs))
        quiet_lo = max(0, quiet_hi - int(round(QUIET_WINDOW_S * fs)))
        if quiet_hi - quiet_lo < fs:  # 1秒未満しか取れない
            raise SystemExit(f"{eid}: 静穏区間が短すぎる(保存窓がonset直前まで届いていない)")
        quiet = gal[quiet_lo:quiet_hi]
        self.g_mean = quiet.mean(axis=0)
        self.up = self.g_mean / np.linalg.norm(self.g_mean)
        self.tilt_deg = float(np.degrees(np.arccos(np.clip(self.up[2], -1, 1))))
        self.R = frame_from_up(self.up)
        rotated = (gal - self.g_mean) @ self.R.T
        self.h = rotated[:, :2]
        self.t_s = ((start_us + np.arange(len(gal)) / fs * 1e6) - onset_us) / 1e6
        self.azimuth_deg = 0.0  # --ref自身、または未計算時の既定
        self.coherence: float | None = None
        self.lag_ms: int | None = None

    def h_at(self, t_grid: np.ndarray) -> np.ndarray:
        return np.stack([np.interp(t_grid, self.t_s, self.h[:, k]) for k in (0, 1)], axis=1)


def fit_relative_azimuth(ref: DeviceCal, other: DeviceCal) -> tuple[float, float, int]:
    """other を何度回すと ref の水平基底に一致するか(Procrustes最適回転)。

    戻り値: (azimuth_deg, coherence, best_lag_ms)。lag は other 側の検出onsetが
    ref に対してどれだけ遅れて記録されたか(クロック・検出アルゴリズムの差。方位の
    意味には影響しないが診断に出す)。
    """
    t_grid = np.arange(TAP_WINDOW_S[0], TAP_WINDOW_S[1], 0.01)
    v_ref = ref.h_at(t_grid)
    best = None
    for tau_ms in range(-LAG_RANGE_MS, LAG_RANGE_MS + 1, LAG_STEP_MS):
        v_other = other.h_at(t_grid + tau_ms / 1000.0)
        a, b = v_ref, v_other
        A = np.sum(a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1])
        B = np.sum(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        e1, e2 = np.sqrt(np.sum(a ** 2)), np.sqrt(np.sum(b ** 2))
        coherence = float(np.hypot(A, B) / (e1 * e2)) if e1 * e2 > 0 else 0.0
        theta = float(np.degrees(np.arctan2(B, A)))
        if best is None or coherence > best[0]:
            best = (coherence, theta, tau_ms)
    coherence, theta, tau_ms = best
    return theta, coherence, tau_ms


def load_calibrations(events_table, bucket: str, eids: list[str]) -> list[DeviceCal]:
    from common import store
    import boto3

    s3 = boto3.client("s3")
    cals = []
    seen_devices: set[int] = set()
    for eid in eids:
        device_id = device_of(eid)
        if device_id in seen_devices:
            raise SystemExit(f"デバイス{device_id:04d}のイベントが重複している: {eid}")
        seen_devices.add(device_id)
        item = events_table.get_item(Key={"event_id": eid}).get("Item")
        if not item:
            raise SystemExit(f"イベントが見つからない: {eid}")
        onset_us = int(item["onset_us"])
        waveform_prefix = item.get("waveform_prefix")
        if not waveform_prefix:
            raise SystemExit(f"{eid}: waveform_prefix が無い(まだ events/ へ永久保存されていない)")
        gal, start_us, fs = store.load_event(s3, bucket, eid)
        if len(gal) == 0:
            raise SystemExit(f"{eid}: 波形が空(events/{eid}/ が無いかもしれない)")
        cals.append(DeviceCal(eid, device_id, onset_us, gal, start_us, fs))
    return cals


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="人工加振イベントから傾き・相対方位を較正する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("events", nargs="+", help="同時に加振した各機のイベントID(例 0001-59541742)")
    p.add_argument("--ref", type=int, help="方位の基準にするdevice_id(既定: 最小のdevice_id)")
    p.add_argument("--bucket", help="データバケット(既定: NAMZ_BUCKET/NAMZ_RAW_BUCKET/terraform)")
    p.add_argument("--events-table", default=os.environ.get("NAMZ_EVENTS_TABLE"),
                   help="イベントのDynamoDBテーブル名(既定: 環境変数 NAMZ_EVENTS_TABLE)")
    p.add_argument("--devices-table", default=os.environ.get("NAMZ_DEVICES_TABLE"),
                   help="デバイス台帳のDynamoDBテーブル名(既定: 環境変数 NAMZ_DEVICES_TABLE)")
    p.add_argument("--write", action="store_true", help="namazu-devices に書き込む(既定は表示のみ)")
    p.add_argument("--yes", "-y", action="store_true", help="書き込み前の確認プロンプトを省略")
    args = p.parse_args(argv)

    if len(args.events) < 2:
        raise SystemExit("2機以上のイベントIDが要る(相対方位を較正するため)")

    awsenv.ensure_region()
    import boto3

    events_table_name = resolve_table(args.events_table, "NAMZ_EVENTS_TABLE", None)
    events_table = boto3.resource("dynamodb").Table(events_table_name)
    bucket = detectlab.resolve_bucket(args.bucket)

    cals = load_calibrations(events_table, bucket, args.events)
    ref_id = args.ref if args.ref is not None else min(c.device_id for c in cals)
    ref = next((c for c in cals if c.device_id == ref_id), None)
    if ref is None:
        raise SystemExit(f"--ref {ref_id:04d} に対応するイベントが渡されていない")

    for c in cals:
        if c is ref:
            continue
        theta, coherence, lag_ms = fit_relative_azimuth(ref, c)
        c.azimuth_deg, c.coherence, c.lag_ms = theta, coherence, lag_ms

    print(f"基準デバイス: {ref_id:04d}\n")
    print(f"{'device':>6}  {'tilt_deg':>9}  {'azimuth_deg':>11}  {'coherence':>9}  {'lag_ms':>7}  event")
    for c in sorted(cals, key=lambda c: c.device_id):
        coh = f"{c.coherence:.3f}" if c.coherence is not None else "  (ref)"
        lag = f"{c.lag_ms:+d}" if c.lag_ms is not None else "-"
        print(f"{c.device_id:06d}  {c.tilt_deg:9.3f}  {c.azimuth_deg:11.3f}  {coh:>9}  {lag:>7}  {c.eid}")
        if c.coherence is not None and c.coherence < COHERENCE_WARN_THRESHOLD:
            print(f"  警告: {c.device_id:04d} のコヒーレンスが低い({c.coherence:.3f})。"
                  "タップが弱いか2機が剛結できていない疑いがある。信用しすぎるな")

    if not args.write:
        print("\n(--write を付けなかったので namazu-devices への書き込みはしない)")
        return 0

    devices_table_name = resolve_table(args.devices_table, "NAMZ_DEVICES_TABLE", "devices_table")
    devices_table = boto3.resource("dynamodb").Table(devices_table_name)
    calibrated_at_us = int(datetime.now(timezone.utc).timestamp() * 1e6)
    source_events = ",".join(c.eid for c in cals)

    print(f"\n書き込み先: {devices_table_name}  calibrated_at_us={calibrated_at_us}")
    if not args.yes:
        try:
            ok = input("この内容で namazu-devices を上書きするか? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            ok = False
        if not ok:
            raise SystemExit("中止した")

    for c in cals:
        devices_table.update_item(
            Key={"device_id": c.device_id},
            UpdateExpression=(
                "SET tilt_up = :up, tilt_deg = :tilt, azimuth_deg = :az, "
                "calibration_ref_device = :ref, calibrated_at_us = :cal_us, "
                "calibration_events = :src"
            ),
            ExpressionAttributeValues={
                ":up": [Decimal(str(round(float(x), 6))) for x in c.up],
                ":tilt": Decimal(str(round(c.tilt_deg, 3))),
                ":az": Decimal(str(round(c.azimuth_deg, 3))),
                ":ref": ref_id,
                ":cal_us": calibrated_at_us,
                ":src": source_events,
            },
        )
        print(f"  device {c.device_id:04d} 更新完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
