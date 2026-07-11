"""jismo — 気象庁 計測震度の算出ライブラリ。

- `jma_fft`   : FFTベースの正式アルゴリズム（真実の源）
- `filters`   : 周波数領域フィルタ Y(f) の定義
- `fir`       : Y(f) を近似する線形位相FIRの設計（リアルタイム版・ファーム用）
- `realtime`  : FIRによるストリーミング計測震度
- `rounding`  : 気象庁の丸め規則・震度階級への変換
"""

from .jma_fft import measured_intensity, filtered_composite
from .filters import jma_filter_response
from .rounding import jma_round, intensity_scale

__all__ = [
    "measured_intensity",
    "filtered_composite",
    "jma_filter_response",
    "jma_round",
    "intensity_scale",
]
