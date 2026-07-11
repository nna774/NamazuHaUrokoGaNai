"""バックテスト / 計測震度の算出CLI。

CSV (t_us,x_gal,y_gal,z_gal) を読み、
- FFT版（正式）の計測震度
- リアルタイムFIR版の震度トレース（移動窓）
を計算し、両者を比較する。

使い方:
    python backtest.py capture.csv
    python gen_synthetic.py --kind quake --amp 20 | python backtest.py -
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from jismo import jma_fft
from jismo.fir import group_delay_samples
from jismo.realtime import RealtimeIntensity, WINDOW_SECONDS


def load_csv(path: str) -> tuple[np.ndarray, float]:
    """CSVを読み (N,3)[gal] とサンプルレートを返す。"""
    f = sys.stdin if path == "-" else open(path)
    with f:
        header = f.readline()  # skip header
        rows = [line.split(",") for line in f if line.strip()]
    arr = np.array(rows, dtype=float)
    t_us = arr[:, 0]
    data = arr[:, 1:4]
    if len(t_us) > 1:
        dt = np.median(np.diff(t_us)) / 1e6
        fs = 1.0 / dt
    else:
        fs = 100.0
    return data, fs


def realtime_trace(data: np.ndarray, fs: float, step: int) -> tuple[np.ndarray, np.ndarray]:
    """FIR版の震度トレースを `step` サンプルおきに返す (時刻[s], 震度)。"""
    rt = RealtimeIntensity(fs)
    times, vals = [], []
    for i in range(data.shape[0]):
        rt.push(data[i, 0], data[i, 1], data[i, 2])
        if i % step == 0:
            times.append(i / fs)
            vals.append(rt.current_intensity())
    return np.array(times), np.array(vals)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv", help="CSV path or '-' for stdin")
    p.add_argument("--step", type=int, default=25, help="リアルタイム震度の評価間隔[サンプル]")
    p.add_argument("--trace", action="store_true", help="震度トレースを出力")
    args = p.parse_args()

    data, fs = load_csv(args.csv)
    n = data.shape[0]
    print(f"# samples={n} fs={fs:.2f}Hz duration={n/fs:.1f}s", file=sys.stderr)

    # FFT版（正式）: 全区間、ただし60秒窓を超える場合は最大振幅を含む窓で
    win = int(WINDOW_SECONDS * fs)
    if n <= win:
        res = jma_fft.measured_intensity(data[:, 0], data[:, 1], data[:, 2], fs)
    else:
        # 合成加速度ピーク位置を含む末尾寄りの60秒窓
        comp = jma_fft.filtered_composite(data[:, 0], data[:, 1], data[:, 2], fs)
        peak = int(np.argmax(comp))
        start = max(0, min(peak - win // 2, n - win))
        seg = data[start:start + win]
        res = jma_fft.measured_intensity(seg[:, 0], seg[:, 1], seg[:, 2], fs)

    print(f"[FFT] 計測震度 I={res.intensity:.1f} (raw {res.intensity_raw:.3f}) "
          f"震度{res.scale}  a0={res.a0:.3f}gal peak={res.peak_gal:.3f}gal")

    # リアルタイムFIR版
    times, vals = realtime_trace(data, fs, args.step)
    if len(vals):
        gd = group_delay_samples()
        print(f"[FIR] 最大リアルタイム震度 I={vals.max():.1f} "
              f"(群遅延 {gd}サンプル≈{gd/fs:.2f}s)")
        diff = abs(vals.max() - res.intensity)
        print(f"[diff] |FIR_max - FFT| = {diff:.2f}")

    if args.trace:
        print("t_s,rt_intensity")
        for t, v in zip(times, vals):
            print(f"{t:.2f},{v:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
