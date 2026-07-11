"""FIRによるストリーミング計測震度（リアルタイム版）。

ファームウェアの `firmware/lib/Shindo` はこのクラスの逐次処理(push)を
そのまま C++ で写経したもの。バックテストで FFT版と数値照合してから信用する。
"""

from __future__ import annotations

from collections import deque

import numpy as np
from scipy.signal import fftconvolve

from .fir import DEFAULT_NUMTAPS, design_fir
from .jma_fft import EXCEEDANCE_SECONDS, exceedance_amplitude
from .rounding import jma_round, intensity_scale

WINDOW_SECONDS = 60.0  # 計測震度を評価する移動窓 [秒]


class RealtimeIntensity:
    """逐次push型のリアルタイム計測震度計。"""

    def __init__(self, fs: float, numtaps: int = DEFAULT_NUMTAPS,
                 window_seconds: float = WINDOW_SECONDS):
        self.fs = float(fs)
        self.taps = design_fir(fs, numtaps)
        self.numtaps = numtaps
        self._win = int(round(window_seconds * fs))
        # 各軸の直近 numtaps サンプル（FIR畳み込み用）
        self._buf = {ax: deque([0.0] * numtaps, maxlen=numtaps) for ax in "xyz"}
        # フィルタ後合成加速度の移動窓リングバッファ
        self._composite = deque(maxlen=self._win)

    def push(self, ax: float, ay: float, az: float) -> float:
        """1サンプル入れ、フィルタ後の合成加速度[gal]を返す。"""
        filt = {}
        for name, val in (("x", ax), ("y", ay), ("z", az)):
            b = self._buf[name]
            b.append(float(val))
            # FIR: taps を最新→過去の順に内積（taps は対称なので順序不問だが素直に）
            filt[name] = float(np.dot(self.taps[::-1], b))
        comp = (filt["x"] ** 2 + filt["y"] ** 2 + filt["z"] ** 2) ** 0.5
        self._composite.append(comp)
        return comp

    def ready(self) -> bool:
        """震度を出せるだけのデータ（0.3秒ぶん）が溜まったか。"""
        return len(self._composite) >= int(round(EXCEEDANCE_SECONDS * self.fs))

    def current_intensity(self) -> float:
        """移動窓の現在の計測震度を返す（気象庁丸め後）。"""
        if not self.ready():
            return 0.0
        comp = np.fromiter(self._composite, dtype=float)
        a0 = exceedance_amplitude(comp, self.fs)
        if a0 <= 0:
            return 0.0
        return jma_round(2.0 * np.log10(a0) + 0.94)

    def scale(self) -> str:
        return intensity_scale(self.current_intensity())

    # --- オフライン一括処理（バックテスト用・push と等価だが高速） ---
    def filtered_composite(self, ax: np.ndarray, ay: np.ndarray, az: np.ndarray) -> np.ndarray:
        """FIRで3成分をフィルタしベクトル合成した波形を返す（'full'先頭を捨てて因果整列）。"""
        fx = fftconvolve(np.asarray(ax, float), self.taps)[: len(ax)]
        fy = fftconvolve(np.asarray(ay, float), self.taps)[: len(ay)]
        fz = fftconvolve(np.asarray(az, float), self.taps)[: len(az)]
        return np.sqrt(fx * fx + fy * fy + fz * fz)
