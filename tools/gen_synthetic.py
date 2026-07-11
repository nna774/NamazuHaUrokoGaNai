"""合成加速度波形の生成（テスト・デモ用）。

CSV形式: t_us,x_gal,y_gal,z_gal
"""

from __future__ import annotations

import argparse
import sys

import numpy as np


def synth_quake(fs: float, seconds: float, amp_gal: float = 20.0,
                center_hz: float = 3.0, seed: int = 0) -> np.ndarray:
    """減衰する帯域制限ノイズで「地震っぽい」3成分波形を作る。shape=(N,3)。"""
    rng = np.random.default_rng(seed)
    n = int(fs * seconds)
    t = np.arange(n) / fs
    # ガウス的な包絡（立ち上がり→減衰）
    envelope = np.exp(-((t - seconds * 0.35) ** 2) / (2 * (seconds * 0.18) ** 2))
    out = np.zeros((n, 3))
    for axis in range(3):
        # center_hz 付近の帯域制限ノイズ
        white = rng.standard_normal(n)
        spec = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n, 1.0 / fs)
        band = np.exp(-((freqs - center_hz) ** 2) / (2 * 1.5 ** 2))
        shaped = np.fft.irfft(spec * band, n=n)
        shaped = shaped / (np.abs(shaped).max() + 1e-12)
        out[:, axis] = shaped * envelope * amp_gal * (0.7 + 0.3 * rng.random())
    return out


def synth_noise(fs: float, seconds: float, rms_gal: float = 0.2, seed: int = 1) -> np.ndarray:
    """静置ノイズ（センサノイズフロア模擬）。"""
    rng = np.random.default_rng(seed)
    n = int(fs * seconds)
    return rng.standard_normal((n, 3)) * rms_gal


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fs", type=float, default=100.0)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--kind", choices=["quake", "noise"], default="quake")
    p.add_argument("--amp", type=float, default=20.0)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    if args.kind == "quake":
        data = synth_quake(args.fs, args.seconds, amp_gal=args.amp, seed=args.seed)
    else:
        data = synth_noise(args.fs, args.seconds, rms_gal=args.amp, seed=args.seed)

    n = data.shape[0]
    print("t_us,x_gal,y_gal,z_gal")
    for i in range(n):
        t_us = int(round(i * 1e6 / args.fs))
        print(f"{t_us},{data[i,0]:.5f},{data[i,1]:.5f},{data[i,2]:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
