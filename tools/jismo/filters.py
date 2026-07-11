"""気象庁 計測震度フィルタ Y(f) の定義。

Y(f) = W_period(f) * W_highcut(f) * W_lowcut(f)

参考: 気象庁「計測震度の算出方法」
https://www.data.jma.go.jp/eqev/data/kyoshin/kaisetu/calc_sindo.htm
"""

from __future__ import annotations

import numpy as np

HIGHCUT_F0 = 10.0   # ハイカットフィルタの基準周波数 [Hz]
LOWCUT_F0 = 0.5     # ローカットフィルタの基準周波数 [Hz]

# ハイカット多項式係数（気象庁定義）
_HIGHCUT_COEFFS = (0.694, 0.241, 0.0557, 0.009664, 0.00134, 0.000155)


def period_effect(freqs: np.ndarray) -> np.ndarray:
    """周期補正フィルタ W_p(f) = sqrt(1/f)。DC(f=0)は0とする。"""
    w = np.zeros_like(freqs, dtype=float)
    nonzero = freqs > 0
    w[nonzero] = np.sqrt(1.0 / freqs[nonzero])
    return w


def highcut(freqs: np.ndarray) -> np.ndarray:
    """ハイカットフィルタ W_h(f)。x = f / 10Hz。"""
    x = freqs / HIGHCUT_F0
    denom = np.ones_like(x, dtype=float)
    for i, c in enumerate(_HIGHCUT_COEFFS):
        denom = denom + c * x ** (2 * (i + 1))
    return 1.0 / np.sqrt(denom)


def lowcut(freqs: np.ndarray) -> np.ndarray:
    """ローカットフィルタ W_l(f) = sqrt(1 - exp(-(f/0.5)^3))。DCは0。"""
    x = np.zeros_like(freqs, dtype=float)
    nonzero = freqs > 0
    x[nonzero] = freqs[nonzero] / LOWCUT_F0
    return np.sqrt(1.0 - np.exp(-(x ** 3)))


def jma_filter_response(freqs: np.ndarray) -> np.ndarray:
    """周波数配列に対する Y(f) の振幅応答を返す。"""
    freqs = np.asarray(freqs, dtype=float)
    return period_effect(freqs) * highcut(freqs) * lowcut(freqs)
