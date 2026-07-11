"""気象庁の丸め規則と震度階級への変換。"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal


def jma_round(intensity: float) -> float:
    """計測震度 I を気象庁規則で丸める。

    「小数第3位を四捨五入し，小数第2位を切り捨てた数値」。
    例: 4.678 -> 4.68(第3位四捨五入) -> 4.6(第2位切り捨て)
    """
    two = Decimal(str(intensity)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return math.floor(two * 10) / 10.0


def intensity_scale(intensity: float) -> str:
    """計測震度から気象庁の震度階級を返す。"""
    i = intensity
    if i < 0.5:
        return "0"
    if i < 1.5:
        return "1"
    if i < 2.5:
        return "2"
    if i < 3.5:
        return "3"
    if i < 4.5:
        return "4"
    if i < 5.0:
        return "5弱"
    if i < 5.5:
        return "5強"
    if i < 6.0:
        return "6弱"
    if i < 6.5:
        return "6強"
    return "7"
