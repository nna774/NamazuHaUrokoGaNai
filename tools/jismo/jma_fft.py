"""FFTベースの計測震度算出（正式アルゴリズム・真実の源）。

入力は3成分の加速度 [gal = cm/s^2]。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .filters import jma_filter_response
from .rounding import jma_round, intensity_scale

# a0 を求める際の「合計超過時間」[秒]（気象庁定義）
EXCEEDANCE_SECONDS = 0.3


def detrend(signal: np.ndarray) -> np.ndarray:
    """線形トレンド（直流＋傾き）を除去する。

    Y(f) は f=0 で 0 なので直流は落ちるが、**傾きは落ちない**。センサの傾斜変化や
    熱ドリフトは記録内で加速度がランプ状に動く形になり、これが残ると
    `_apply_filter` の巡回畳み込みで記録の終端と始端の段差になって端でリンギングする。

    気象庁の手法が想定するのは「静止に始まり静止に終わる地震記録」なので元の定義に
    この処理は無いが、こちらは連続ストリームを任意の位置で切った窓を渡している。
    ドリフトは地動ではないので、除いてから掛ける方が定義に忠実である。
    詳細は docs/intensity_pitfalls.md。
    """
    n = signal.size
    if n < 2:
        return np.zeros_like(signal, dtype=float)
    t = np.arange(n, dtype=float)
    return signal - np.polyval(np.polyfit(t, signal, 1), t)


def _apply_filter(signal: np.ndarray, fs: float) -> np.ndarray:
    """1成分の加速度波形に周波数領域で Y(f) を掛け、時間波形に戻す。"""
    signal = detrend(signal)
    n = signal.size
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    filtered = spectrum * jma_filter_response(freqs)
    return np.fft.irfft(filtered, n=n)


def filtered_composite(ax: np.ndarray, ay: np.ndarray, az: np.ndarray, fs: float) -> np.ndarray:
    """3成分にフィルタを掛け、ベクトル合成した加速度波形 a(t) [gal] を返す。"""
    ax = np.asarray(ax, dtype=float)
    ay = np.asarray(ay, dtype=float)
    az = np.asarray(az, dtype=float)
    fx = _apply_filter(ax, fs)
    fy = _apply_filter(ay, fs)
    fz = _apply_filter(az, fs)
    return np.sqrt(fx * fx + fy * fy + fz * fz)


def exceedance_amplitude(composite: np.ndarray, fs: float,
                         seconds: float = EXCEEDANCE_SECONDS) -> float:
    """|a(t)| >= a0 となる合計時間が `seconds` 以上になる最大の a0 を返す。

    サンプル数 k = round(seconds * fs) とし、降順ソートの k 番目の値。
    fs=100Hz, seconds=0.3 なら 30番目（記事の「降順30位」）。
    """
    k = int(round(seconds * fs))
    if composite.size < k or k < 1:
        raise ValueError(f"波形が短すぎる: {composite.size} samples < {k}")
    # k番目に大きい値。partition で十分。
    part = np.partition(composite, -k)[-k:]
    return float(part.min())


@dataclass
class IntensityResult:
    a0: float          # 基準加速度 [gal]
    intensity_raw: float   # I = 2 log10(a0) + 0.94（丸め前）
    intensity: float       # 気象庁規則で丸めた計測震度
    scale: str             # 震度階級（"0", "5弱" など）
    peak_gal: float        # フィルタ後合成加速度のピーク


def intensity_from_composite(composite: np.ndarray, fs: float,
                             seconds: float = EXCEEDANCE_SECONDS) -> IntensityResult:
    """フィルタ後合成加速度 a(t) [gal] から計測震度を算出する。

    合成波形を既に持っている呼び出し側（端を落としたい detect 等）が
    フィルタを二度掛けずに済むように分けてある。
    """
    a0 = exceedance_amplitude(composite, fs, seconds)
    if a0 <= 0:
        raw = float("-inf")
    else:
        raw = 2.0 * np.log10(a0) + 0.94
    rounded = jma_round(raw) if a0 > 0 else 0.0
    return IntensityResult(
        a0=a0,
        intensity_raw=raw,
        intensity=rounded,
        scale=intensity_scale(rounded),
        peak_gal=float(composite.max()),
    )


def measured_intensity(ax: np.ndarray, ay: np.ndarray, az: np.ndarray, fs: float,
                       seconds: float = EXCEEDANCE_SECONDS) -> IntensityResult:
    """3成分加速度 [gal] から計測震度を算出する。"""
    return intensity_from_composite(filtered_composite(ax, ay, az, fs), fs, seconds)
