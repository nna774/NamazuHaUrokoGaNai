"""jismo — 気象庁 計測震度の算出ライブラリ。

- `jma_fft`   : FFTベースの正式アルゴリズム（真実の源。numpyのみ）
- `filters`   : 周波数領域フィルタ Y(f) の定義（numpyのみ）
- `rounding`  : 気象庁の丸め規則・震度階級への変換
- `fir`       : Y(f) を近似する線形位相FIRの設計（scipy必要・明示import）
- `realtime`  : FIRによるストリーミング計測震度（scipy必要・明示import）

クラウド(detect/api Lambda)は FFT版しか使わないため、パッケージ初期化では
numpyのみに依存する軽量モジュールだけを公開する。fir/realtime は
`from jismo.realtime import RealtimeIntensity` のように明示的に読み込むこと。
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
