"""計測震度の時系列グラフ（イベント波形から複数デバイスを重ね描き）。

https://qiita.com/compo031/items/298f946e5ca7a3e0e5b7 のような、時間経過に対して
計測震度がどう立ち上がり・減衰するかを見るための事後解析ビュー。`jismo.realtime.
RealtimeIntensity`（ファームと数値照合済みのFIR・60秒移動窓）を保存済みイベント波形に
逐次pushし、一定間隔ごとの計測震度をサンプリングしてプロットする。

    python tools/intensity_timeline.py --event 0001-59580602 0002-59580602 \
        --out /tmp/intensity_timeline.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detectlab import _s3_client, resolve_bucket  # noqa: E402

_LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda"
if str(_LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(_LAMBDA_DIR))

from jismo.realtime import intensity_timeline as compute_timeline  # noqa: E402
from jismo.rounding import intensity_scale  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--event", nargs="+", required=True, help="event_id (複数可。同一地震の複数デバイスを重ね描き)")
    p.add_argument("--step", type=float, default=0.5, help="サンプリング間隔[秒]（既定0.5秒）")
    p.add_argument("--bucket", help="rawバケット名（省略時はterraform outputから解決）")
    p.add_argument("--no-cache", dest="use_cache", action="store_false", default=True)
    p.add_argument("--out", required=True, help="出力PNGパス")
    p.add_argument("--xlim", nargs=2, type=float, metavar=("START", "END"),
                   help="表示する経過時間の範囲[秒]（既定は全範囲）")
    args = p.parse_args()

    bucket = resolve_bucket(args.bucket)
    s3 = _s3_client(args.use_cache)

    from common import store

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    for name in ("Hiragino Sans", "IPAexGothic", "Noto Sans CJK JP"):
        if any(name in f.name for f in fm.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break

    fig, ax = plt.subplots(figsize=(10, 5))

    series = []
    for eid in args.event:
        gal, start_us, fs = store.load_event(s3, bucket, eid)
        if gal.shape[0] == 0:
            print(f"警告: {eid} の波形が空", file=sys.stderr)
            continue
        device_id = eid.split("-", 1)[0]
        ts, vals = compute_timeline(gal, fs, args.step)
        series.append((eid, device_id, start_us, ts, vals))

    if not series:
        raise SystemExit("プロットできる波形が無い")

    t0 = min(start_us for _, _, start_us, _, _ in series)
    peaks = []
    for eid, device_id, start_us, ts, vals in series:
        offset = (start_us - t0) / 1e6
        t = ts + offset
        line, = ax.plot(t, vals, label=f"{int(device_id)}号機 ({eid})", linewidth=1.2)
        peak_i = int(np.argmax(vals))
        peaks.append((device_id, line.get_color(), t[peak_i], vals[peak_i]))
    # ピーク点にはドットだけ打ち、値は左上にまとめて注記する（ピーク位置に文字を置くと
    # データの形次第で重なりやすいため、固定位置にまとめた方が読みやすい）。
    for device_id, color, peak_t, peak_v in peaks:
        ax.scatter([peak_t], [peak_v], color=color, s=20, zorder=5,
                  edgecolor="white", linewidth=0.5)
    for i, (device_id, color, _t, peak_v) in enumerate(peaks):
        ax.text(0.01, 0.97 - 0.06 * i,
               f"{int(device_id)}号機 ピーク I={peak_v:.1f} 震度{intensity_scale(peak_v)}",
               transform=ax.transAxes, color=color, fontsize=8, va="top", ha="left",
               bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1))

    ax.set_xlabel("経過時間 [秒]")
    ax.set_ylabel("計測震度")
    ax.set_title(f"計測震度の時系列（{args.step}秒間隔・60秒移動窓）")
    if args.xlim:
        ax.set_xlim(args.xlim[0], args.xlim[1])
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"書き出し: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
