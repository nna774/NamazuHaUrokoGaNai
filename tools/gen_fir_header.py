"""FIR係数を firmware/lib/Shindo/JmaFirTaps.h として書き出す。

    python gen_fir_header.py [--fs 100] [--numtaps 511]
"""

from __future__ import annotations

import argparse
import os

from jismo.fir import design_fir, export_c_array, DEFAULT_NUMTAPS

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, "..", "firmware", "lib", "Shindo", "JmaFirTaps.h"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fs", type=float, default=100.0)
    p.add_argument("--numtaps", type=int, default=DEFAULT_NUMTAPS)
    p.add_argument("--out", default=DEFAULT_OUT)
    args = p.parse_args()

    taps = design_fir(args.fs, args.numtaps)
    body = export_c_array(taps)
    content = (
        "#pragma once\n"
        "// 気象庁計測震度フィルタ Y(f) を近似する線形位相FIR係数。\n"
        "// tools/gen_fir_header.py で生成。手で編集しないこと。\n"
        f"// fs={args.fs}Hz numtaps={args.numtaps}\n\n"
        f"{body}\n"
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(content)
    print(f"wrote {args.out} ({taps.size} taps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
