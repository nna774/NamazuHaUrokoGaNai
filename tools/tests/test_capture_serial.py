import os
import re

import pytest

from capture_serial import SENSOR_MG_PER_LSB, resolve_scale

FIRMWARE_LIB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "firmware", "lib",
)

# capture_serial のセンサ名 -> ファームのドライバディレクトリ
DRIVER_DIRS = {"iis3dhhc": "Iis3dhhc", "adxl355": "Adxl355"}


def test_scale_overrides_sensor():
    assert resolve_scale("adxl355", 1.5) == 1.5


def test_sensor_looks_up_table():
    assert resolve_scale("iis3dhhc", None) == 0.076


def test_neither_is_an_error():
    # 既定値で黙って換算されると震度が一桁変わるので、必ず落とす。
    with pytest.raises(ValueError):
        resolve_scale(None, None)


@pytest.mark.parametrize("sensor,dirname", sorted(DRIVER_DIRS.items()))
def test_scale_matches_firmware(sensor, dirname):
    """ファームの scaleMgPerLsb() と表が食い違っていないこと。

    ここがずれると、キャプチャした静穏ノイズや震度が黙って別の値になる。
    """
    path = os.path.join(FIRMWARE_LIB, dirname, f"{dirname}.h")
    with open(path) as f:
        src = f.read()
    m = re.search(r"scaleMgPerLsb\(\)\s*const\s*override\s*{\s*return\s*([0-9.eE+-]+)f?;", src)
    assert m, f"{path} から scaleMgPerLsb() を読めない"
    assert float(m.group(1)) == SENSOR_MG_PER_LSB[sensor]
