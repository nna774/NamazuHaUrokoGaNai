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


def scale_ordinal(intensity: float) -> int:
    """震度階級の序数（0..9）。0,1,2,3,4,5弱,5強,6弱,6強,7 の順。
    通知のエスカレーション判定（クラスが上がったか）に使う。"""
    if intensity < 0.5:
        return 0
    if intensity < 1.5:
        return 1
    if intensity < 2.5:
        return 2
    if intensity < 3.5:
        return 3
    if intensity < 4.5:
        return 4
    if intensity < 5.0:
        return 5
    if intensity < 5.5:
        return 6
    if intensity < 6.0:
        return 7
    if intensity < 6.5:
        return 8
    return 9


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
