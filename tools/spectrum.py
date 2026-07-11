"""キャプチャCSVのノイズスペクトルを見る。ノイズ源の切り分け用。

    python spectrum.py rest.csv

各軸のRMSと、卓越する周波数(上位)を表示する。
- 1〜5Hz 付近が強い → 足音・体動など低周波の機械振動
- 10〜30Hz が強い → 机・床の構造振動、機器のファン等
- 特定の鋭いピーク → 電源/電気的ノイズや回転機械の可能性
"""

from __future__ import annotations

import argparse
import sys

import numpy as np


def load_csv(path: str):
    f = sys.stdin if path == "-" else open(path)
    with f:
        f.readline()
        rows = [l.split(",") for l in f if l.strip()]
    a = np.array(rows, dtype=float)
    t_us = a[:, 0]
    fs = 1.0 / (np.median(np.diff(t_us)) / 1e6) if len(t_us) > 1 else 100.0
    return a[:, 1:4], fs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("--top", type=int, default=6)
    args = p.parse_args()

    data, fs = load_csv(args.csv)
    n = data.shape[0]
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    print(f"# samples={n} fs={fs:.2f}Hz")

    for i, ax in enumerate("xyz"):
        sig = data[:, i] - data[:, i].mean()  # DC(重力含む)除去
        rms = np.sqrt(np.mean(sig ** 2))
        spec = np.abs(np.fft.rfft(sig)) / n
        spec[0] = 0
        idx = np.argsort(spec)[::-1][:args.top]
        idx = np.sort(idx)
        peaks = ", ".join(f"{freqs[k]:.2f}Hz" for k in idx)
        print(f"{ax}: RMS={rms:.3f}gal  卓越周波数: {peaks}")

    # 帯域別のパワー割合（低周波か高周波か）
    print("\n帯域別パワー割合(全軸合成):")
    total = np.zeros_like(freqs)
    for i in range(3):
        sig = data[:, i] - data[:, i].mean()
        s = np.abs(np.fft.rfft(sig)) ** 2
        s[0] = 0
        total += s
    bands = [(0, 1), (1, 5), (5, 10), (10, 20), (20, 50)]
    tp = total.sum() or 1.0
    for lo, hi in bands:
        m = (freqs >= lo) & (freqs < hi)
        print(f"  {lo:2d}-{hi:2d}Hz: {100*total[m].sum()/tp:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
