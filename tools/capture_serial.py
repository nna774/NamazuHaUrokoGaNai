"""ファームウェアのシリアル出力をCSVに保存する。

ファーム側は 1行1サンプルで `t_us,x_lsb,y_lsb,z_lsb` を出力する想定。
--scale で LSB->gal に換算して保存する（IIS3DHHCの既定スケールを内蔵）。

使い方:
    python capture_serial.py --port /dev/tty.usbserial-XXXX --seconds 60 > cap.csv
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial  # pyserial
except ImportError:
    serial = None

# IIS3DHHC: ±2.5g / 16bit -> 0.076 mg/LSB。gal = mg * 0.980665e-2 * 1000?
# mg -> gal: 1 g = 980.665 gal, 1 mg = 0.980665 gal。
IIS3DHHC_MG_PER_LSB = 0.076
MG_TO_GAL = 0.980665


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--scale", type=float, default=IIS3DHHC_MG_PER_LSB,
                   help="mg/LSB。生LSB入力をgalへ換算する係数")
    p.add_argument("--raw", action="store_true", help="換算せずLSBのまま保存")
    args = p.parse_args()

    if serial is None:
        print("pyserial 未インストール: pip install pyserial", file=sys.stderr)
        return 1

    ser = serial.Serial(args.port, args.baud, timeout=1)
    print("t_us,x_gal,y_gal,z_gal" if not args.raw else "t_us,x_lsb,y_lsb,z_lsb")
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
            g = [v * args.scale * MG_TO_GAL for v in xyz]
            print(f"{t_us},{g[0]:.5f},{g[1]:.5f},{g[2]:.5f}")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
