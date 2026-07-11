"""地震検知のコアロジック（純関数）。ローカルでもバックテストできるよう副作用を持たない。

jismo（tools/jismo）の計測震度算出を使う。detect Lambda はこれを呼ぶだけ。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from jismo import jma_fft


def amp_for_intensity(intensity: float) -> float:
    """計測震度 I に対応する基準加速度 a0 [gal]。I = 2log10(a0)+0.94 の逆。"""
    return 10.0 ** ((intensity - 0.94) / 2.0)


@dataclass
class Detection:
    onset_us: int          # 揺れの立ち上がり時刻
    max_intensity: float   # 窓全体の正式計測震度（FFT版）
    peak_gal: float        # フィルタ後合成加速度のピーク
    a0: float


def analyze(gal: np.ndarray, fs: float, window_start_us: int,
            threshold: float = 0.5, hold_seconds: float = 2.0) -> Detection | None:
    """窓内に「閾値以上が hold_seconds 継続する揺れ」があれば Detection を返す。

    生活振動（<0.5秒の単発スパイク）は継続時間条件で自然に落ちる。
    """
    if gal.shape[0] < int(fs * hold_seconds):
        return None

    comp = jma_fft.filtered_composite(gal[:, 0], gal[:, 1], gal[:, 2], fs)
    a_th = amp_for_intensity(threshold)
    above = comp >= a_th

    # above が hold_n 連続する最初の位置を探す
    hold_n = int(fs * hold_seconds)
    onset_idx = _first_sustained_run(above, hold_n)
    if onset_idx is None:
        return None

    res = jma_fft.measured_intensity(gal[:, 0], gal[:, 1], gal[:, 2], fs)
    onset_us = int(window_start_us + onset_idx / fs * 1e6)
    return Detection(onset_us=onset_us, max_intensity=res.intensity,
                     peak_gal=float(comp.max()), a0=res.a0)


def _first_sustained_run(mask: np.ndarray, min_len: int) -> int | None:
    """True が min_len 以上連続する最初の開始インデックスを返す。"""
    run = 0
    for i, v in enumerate(mask):
        if v:
            run += 1
            if run >= min_len:
                return i - min_len + 1
        else:
            run = 0
    return None
