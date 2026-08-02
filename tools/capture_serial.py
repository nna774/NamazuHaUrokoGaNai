"""ファームウェアのシリアル出力をCSVに保存する。

ファーム側は 1行1サンプルで `t_us,x_lsb,y_lsb,z_lsb` を出力する想定。
生値のスケールはセンサごとに違うので、`--sensor` か `--scale` で明示する。

使い方:
    python capture_serial.py --sensor iis3dhhc --port /dev/tty.usbserial-XXXX --seconds 60 > cap.csv
    python capture_serial.py --sensor adxl355  --port /dev/tty.usbserial-XXXX --seconds 300 > cap.csv
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    serial = None

# mg -> gal: 1 g = 980.665 gal, 1 mg = 0.980665 gal。
MG_TO_GAL = 0.980665

# センサごとの mg/LSB。ファームの AccelSensor::scaleMgPerLsb() と一致させること。
#   IIS3DHHC: ±2.5g / 16bit
#   ADXL355 : ±2.048g / 20bit（firmware/lib/Adxl355 は最小レンジ固定）
SENSOR_MG_PER_LSB = {
    "iis3dhhc": 0.076,
    "adxl355": 0.00390625,
}


def resolve_scale(sensor: str | None, scale: float | None) -> float:
    """mg/LSB を決める。--scale が優先。どちらも無ければエラー。

    既定値を持たせない。センサが2機種ある以上、既定は 20倍違う値を黙って
    掛ける罠にしかならない（震度が一桁変わる）。
    """
    if scale is not None:
        return scale
    if sensor is not None:
        return SENSOR_MG_PER_LSB[sensor]
    raise ValueError("--sensor か --scale のどちらかを指定すること")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--sensor", choices=sorted(SENSOR_MG_PER_LSB),
                   help="センサ種別。スケールをここから引く")
    p.add_argument("--scale", type=float, default=None,
                   help="mg/LSB を直接指定する（--sensor より優先）")
    p.add_argument("--raw", action="store_true", help="換算せずLSBのまま保存")
    args = p.parse_args()

    if args.raw:
        scale = None
    else:
        try:
            scale = resolve_scale(args.sensor, args.scale)
        except ValueError as e:
            p.error(str(e))
        print(f"[capture] {scale} mg/LSB で gal へ換算する", file=sys.stderr)

    if serial is None:
        print("pyserial 未インストール: pip install pyserial", file=sys.stderr)
        return 1

    ser = serial.Serial(args.port, args.baud, timeout=1)
    print("t_us,x_lsb,y_lsb,z_lsb" if args.raw else "t_us,x_gal,y_gal,z_gal")
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        line = ser.readline().decode("ascii", "ignore").strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) != 4:
            continue
        try:
            t_us = int(parts[0])
            xyz = [int(v) for v in parts[1:4]]
        except ValueError:
            continue
        if args.raw:
            print(f"{t_us},{xyz[0]},{xyz[1]},{xyz[2]}")
        else:
            g = [v * scale * MG_TO_GAL for v in xyz]
            print(f"{t_us},{g[0]:.5f},{g[1]:.5f},{g[2]:.5f}")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
