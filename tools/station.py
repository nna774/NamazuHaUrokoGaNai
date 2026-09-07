"""観測点座標と震源ジオメトリの平面近似。numpy/scipy に依存しない（math/osのみ）。

detectlab.py（scipyに依存する解析本体）から切り出した。detection_range.py・
scan_quakes.pyはここだけに依存すればよく、Lambda（lambda/quake_scan）にも
scipyを持ち込まずに同梱できる。
"""

from __future__ import annotations

import math
import os

# センサ設置点の概略座標(町レベル)。--station / 環境変数 NAMZ_STATION_LATLON で上書き可。
DEFAULT_STATION = (36.936, 138.815)  # 新潟県湯沢町


def hypocentral_km(eq_lat, eq_lon, depth_km, st_lat, st_lon) -> tuple[float, float]:
    """観測点から震源までの距離[km]と震央距離[km]を平面近似で返す。"""
    dlat = (eq_lat - st_lat) * 111.0
    dlon = (eq_lon - st_lon) * 111.0 * math.cos(math.radians((eq_lat + st_lat) / 2))
    epi = math.hypot(dlat, dlon)
    return math.hypot(epi, depth_km), epi


def bearing_deg(eq_lat, eq_lon, st_lat, st_lon) -> float:
    """観測点から見た震源の方位角[度]（真北=0、時計回り）を返す。

    hypocentral_km()と同じ緯度経度の平面近似（大円ではない）を使う——
    観測点から震源までの距離を求めるのと同じ近似モデルで、日本国内スケール
    （〜1000km）では方位角の誤差も実用上問題にならない。
    """
    dlat = (eq_lat - st_lat) * 111.0
    dlon = (eq_lon - st_lon) * 111.0 * math.cos(math.radians((eq_lat + st_lat) / 2))
    return math.degrees(math.atan2(dlon, dlat)) % 360


def parse_station(s: str | None) -> tuple[float, float]:
    src = s or os.environ.get("NAMZ_STATION_LATLON")
    if not src:
        return DEFAULT_STATION
    try:
        lat, lon = (float(x) for x in src.split(","))
        return lat, lon
    except Exception:
        raise SystemExit('--station は "lat,lon" 形式で指定しろ 例: "36.936,138.815"')
