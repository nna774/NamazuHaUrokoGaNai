"""ノイズに埋もれた小さな地震を炙り出すオフライン解析ビュー。

時間波形1本では環境ノイズ(足音・ファン・交通)のRMSに埋もれて見えない過渡を、
- バンドパス後の波形
- スペクトログラム(時間×周波数)
- STA/LTA比(短期/長期エネルギー比。地震観測網のトリガの原理)
の3視点で可視化し、立ち上がり候補時刻を出力する。

データ源はS3の生バッチ(フルレート)。api の /event・/recent は MAX_POINTS 超で
エンベロープに間引かれてスペクトル解析に使えないので、raw/ を直読みする。

    # 20:53 を中心に前後3分をS3から取って解析
    python detectlab.py --at "2026-07-24 20:53" --minutes 3 --out /tmp/2053.png
    # イベントID指定
    python detectlab.py --event 0001-59462454
    # 手元のキャプチャ/合成CSVで
    python detectlab.py --csv cap.csv --band 1 8 --thr 3
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy import signal

JST = ZoneInfo("Asia/Tokyo")

# lambda/common を再利用してS3の raw/・events/ を直読みする。
# detect Lambda が tools/jismo を共有するのと同じクロス参照の思想（逆向き）。
_LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda"
if str(_LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(_LAMBDA_DIR))


# ---- データ取得 ---------------------------------------------------------

def load_csv(path: str) -> tuple[np.ndarray, int, float]:
    """t_us,x_gal,y_gal,z_gal のCSVを読み (gal[N,3], start_us, fs) を返す。"""
    f = sys.stdin if path == "-" else open(path)
    with f:
        f.readline()  # skip header
        rows = [line.split(",") for line in f if line.strip()]
    arr = np.array(rows, dtype=float)
    t_us = arr[:, 0]
    fs = 1.0 / (np.median(np.diff(t_us)) / 1e6) if len(t_us) > 1 else 100.0
    start_us = int(t_us[0]) if len(t_us) else 0
    return arr[:, 1:4], start_us, fs


def resolve_bucket(explicit: str | None) -> str:
    """rawバケット名を --bucket / 環境変数 / terraform output の順で解決。"""
    if explicit:
        return explicit
    env = os.environ.get("NAMZ_RAW_BUCKET") or os.environ.get("NAMZ_DATA_BUCKET")
    if env:
        return env
    tf = Path(__file__).resolve().parent.parent / "terraform"
    try:
        out = subprocess.run(
            ["terraform", "output", "-raw", "data_bucket"],
            cwd=tf, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "rawバケットを解決できない。--bucket か NAMZ_RAW_BUCKET を指定しろ。"
            f" (terraform output も失敗: {exc})"
        )


def load_s3_window(bucket: str, end_us: int, seconds: float) -> tuple[np.ndarray, int, float]:
    from common import store  # 遅延import。CSV経路ではboto3/AWSに触れない。
    import boto3

    return store.load_window(boto3.client("s3"), bucket, end_us, seconds)


def load_s3_event(bucket: str, eid: str) -> tuple[np.ndarray, int, float]:
    from common import store
    import boto3

    return store.load_event(boto3.client("s3"), bucket, eid)


# ---- 信号処理 -----------------------------------------------------------

def bandpass(data: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    """ゼロ位相バンドパス(4次Butterworth)。data (N,3) を各軸に適用。"""
    ny = fs / 2.0
    hi = min(hi, ny * 0.99)
    lo = max(lo, 1e-3)
    sos = signal.butter(4, [lo, hi], btype="band", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, data, axis=0)


def sta_lta(cf: np.ndarray, fs: float, sta_s: float, lta_s: float) -> np.ndarray:
    """特性関数 cf(>=0) の STA/LTA 比。末尾移動平均。LTAが溜まる前は0。"""
    n = len(cf)
    nsta = max(1, int(round(sta_s * fs)))
    nlta = max(nsta + 1, int(round(lta_s * fs)))
    csum = np.concatenate([[0.0], np.cumsum(cf)])
    idx = np.arange(n)

    def trailing_mean(win: int) -> np.ndarray:
        lo = np.maximum(0, idx + 1 - win)
        return (csum[idx + 1] - csum[lo]) / (idx + 1 - lo)

    ratio = trailing_mean(nsta) / np.maximum(trailing_mean(nlta), 1e-12)
    ratio[: min(nlta, n)] = 0.0  # LTA窓が埋まるまでは無効
    return ratio


def detect_onsets(ratio: np.ndarray, fs: float, start_us: int, thr: float) -> list[int]:
    """比が閾値を下から上へ跨いだ立ち上がり時刻(epoch µs)を返す。"""
    above = ratio >= thr
    if len(above) < 2:
        return []
    rising = np.where((~above[:-1]) & (above[1:]))[0] + 1
    return [start_us + int(round(i / fs * 1e6)) for i in rising]


# ---- 出力 ---------------------------------------------------------------

def dump_csv(path: str, data: np.ndarray, start_us: int, fs: float) -> None:
    n = data.shape[0]
    ts = start_us + np.round(np.arange(n) * 1e6 / fs).astype(np.int64)
    with open(path, "w") as f:
        f.write("t_us,x_gal,y_gal,z_gal\n")
        for i in range(n):
            f.write(f"{ts[i]},{data[i, 0]:.5f},{data[i, 1]:.5f},{data[i, 2]:.5f}\n")
    print(f"# dumped {path} ({n} samples)")


def plot(data, band, fs, start_us, ratio, thr, onsets, band_lo, band_hi, out, show):
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    # 日本語ラベルが豆腐にならないよう、環境にある和文フォントを優先。無ければ既定。
    installed = {f.name for f in fm.fontManager.ttflist}
    for jp in ("Hiragino Sans", "Hiragino Kaku Gothic Pro", "YuGothic",
               "Noto Sans CJK JP", "IPAexGothic"):
        if jp in installed:
            plt.rcParams["font.family"] = jp
            break
    plt.rcParams["axes.unicode_minus"] = False

    n = data.shape[0]
    t = np.arange(n) / fs
    fig, axs = plt.subplots(4, 1, figsize=(12, 10), sharex=True)

    raw_ac = data - data.mean(axis=0)  # 重力DCを除いて交流成分だけ見る
    for i, ax in enumerate("xyz"):
        axs[0].plot(t, raw_ac[:, i], lw=0.4, label=ax)
    axs[0].set_ylabel("raw-DC [gal]")
    axs[0].legend(loc="upper right", ncol=3, fontsize=8)
    axs[0].set_title("生波形（重力DC除去。ここでは埋もれて見えない）", fontsize=9, loc="left")

    for i, ax in enumerate("xyz"):
        axs[1].plot(t, band[:, i], lw=0.4, label=ax)
    axs[1].set_ylabel(f"BP {band_lo:g}-{band_hi:g}Hz [gal]")
    axs[1].set_title("バンドパス後（過渡が浮き上がる）", fontsize=9, loc="left")

    vec = np.sqrt((band ** 2).sum(axis=1))
    nper = int(min(256, n))
    if nper >= 8:
        f_s, t_s, sxx = signal.spectrogram(
            vec, fs=fs, nperseg=nper, noverlap=(nper * 7) // 8
        )
        axs[2].pcolormesh(t_s, f_s, 10 * np.log10(sxx + 1e-12), shading="gouraud")
        axs[2].set_ylim(0, min(30, fs / 2))
    axs[2].set_ylabel("freq [Hz]")
    axs[2].set_title("スペクトログラム（過渡が縦のエネルギー筋）", fontsize=9, loc="left")

    axs[3].plot(t, ratio, lw=0.6, color="C3")
    axs[3].axhline(thr, ls="--", color="k", lw=0.8)
    axs[3].set_ylabel("STA/LTA")
    axs[3].set_xlabel("t [s] （窓先頭からの経過）")
    axs[3].set_title(f"STA/LTA比（閾値 {thr:g} 超で検出）", fontsize=9, loc="left")

    for o in onsets:
        ot = (o - start_us) / 1e6
        for a in axs:
            a.axvline(ot, color="m", lw=0.8, alpha=0.6)

    t0 = datetime.fromtimestamp(start_us / 1e6, JST)
    fig.suptitle(f"detectlab  start={t0:%Y-%m-%d %H:%M:%S JST}  fs={fs:.1f}Hz  N={n}")
    fig.tight_layout()
    if out:
        fig.savefig(out, dpi=110)
        print(f"# saved {out}")
    if show:
        plt.show()


# ---- CLI ----------------------------------------------------------------

def at_to_us(s: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=JST).timestamp() * 1e6)
        except ValueError:
            continue
    raise SystemExit(f"--at をパースできない: {s!r}  例: '2026-07-24 20:53'")


def main() -> int:
    p = argparse.ArgumentParser(
        description="ノイズに埋もれた小地震を炙り出す解析ビュー",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--event", help="イベントID（events/<id>/ を連結）")
    src.add_argument("--at", help="窓の中心時刻(JST) 例 '2026-07-24 20:53'")
    src.add_argument("--at-us", type=int, help="窓の中心時刻(epoch µs)")
    src.add_argument("--csv", help="t_us,x_gal,y_gal,z_gal のCSV（- でstdin）")
    p.add_argument("--minutes", type=float, default=3.0, help="窓長[分]（--at系。既定3）")
    p.add_argument("--band", type=float, nargs=2, default=[1.0, 10.0],
                   metavar=("LO", "HI"), help="バンドパス帯域[Hz]（既定 1 10）")
    p.add_argument("--sta", type=float, default=1.0, help="STA窓[秒]（既定1）")
    p.add_argument("--lta", type=float, default=30.0, help="LTA窓[秒]（既定30）")
    p.add_argument("--thr", type=float, default=4.0, help="STA/LTA検出閾値（既定4）")
    p.add_argument("--bucket", help="rawバケット名（既定は NAMZ_RAW_BUCKET / terraform）")
    p.add_argument("--out", help="図の保存先PNG（無指定なら画面表示）")
    p.add_argument("--dump-csv", dest="dump", help="取得した生窓をCSV保存（再利用用）")
    p.add_argument("--show", action="store_true", help="--out 指定時も画面表示する")
    args = p.parse_args()

    if args.csv:
        data, start_us, fs = load_csv(args.csv)
    elif args.event:
        data, start_us, fs = load_s3_event(resolve_bucket(args.bucket), args.event)
    else:
        center = at_to_us(args.at) if args.at else args.at_us
        seconds = args.minutes * 60.0
        end_us = int(center + seconds / 2 * 1e6)
        data, start_us, fs = load_s3_window(resolve_bucket(args.bucket), end_us, seconds)

    n = data.shape[0]
    if n == 0:
        raise SystemExit("波形が空。時刻・バケット・データ保持期間を確認しろ。")

    lo, hi = args.band
    band = bandpass(data, fs, lo, hi)
    cf = (band ** 2).sum(axis=1)
    ratio = sta_lta(cf, fs, args.sta, args.lta)
    onsets = detect_onsets(ratio, fs, start_us, args.thr)

    t0 = datetime.fromtimestamp(start_us / 1e6, JST)
    raw_rms = np.sqrt(np.mean((data - data.mean(axis=0)) ** 2))
    bp_rms = np.sqrt(np.mean(band ** 2))
    print(f"# start={t0:%Y-%m-%d %H:%M:%S JST}  fs={fs:.2f}Hz  N={n}  ({n / fs:.1f}s)")
    print(f"# band={lo:g}-{hi:g}Hz  raw_rms={raw_rms:.4f}gal  bp_rms={bp_rms:.4f}gal"
          f"  STA/LTA peak={ratio.max():.2f}")
    if onsets:
        for o in onsets:
            ot = datetime.fromtimestamp(o / 1e6, JST)
            print(f"  onset候補: {ot:%Y-%m-%d %H:%M:%S.%f} JST  (t+{(o - start_us) / 1e6:.1f}s)")
    else:
        print(f"  onset候補なし（閾値 {args.thr:g} 未達）。--thr を下げる/--band を変えると拾えることも。")

    if args.dump:
        dump_csv(args.dump, data, start_us, fs)

    plot(data, band, fs, start_us, ratio, args.thr, onsets, lo, hi,
         args.out, show=args.show or not args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
