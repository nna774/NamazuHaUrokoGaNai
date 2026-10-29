"""WiFiを動かした窓とOFFの窓でMLX90393の出力がどれだけ違うかを出す（試作）。

`firmware/src/mlx90393_wifitest_main.cpp`（`pio run -e mlx90393-wifitest-c3-gpio34 -t upload`）が
`t_ms,status,x_uT,y_uT,z_uT,temp_C,phase` を吐く（phase 0=WiFi OFF、1=WiFi STA+スキャン連続）。
方位センサを本線のESP32と同居させる前に、WiFiの電流がセンサ出力を動かすかを調べる道具
（[docs/log/2026-10-29-mag-check-tool.md](../docs/log/2026-10-29-mag-check-tool.md)）。

    python mag_wifi_effect.py --port /dev/cu.usbmodem1101 --seconds 420 --save wifi.csv
    python mag_wifi_effect.py --csv wifi.csv

各スキャン窓の中央値から、**前後のOFF窓の中央値の平均**を引く（直線的なドリフトが相殺される）。
窓の先頭`--skip`秒は、無線のON/OFF切替直後の過渡なので捨てる。差の平均と標準誤差、
窓内の標準偏差の比(WiFiで荒れるか)を出す。判定は「差の平均が3σ(標準誤差)を超え、かつ
センサの量子化(0.15µT)を超える」を有意とみなす。差は水平半径(`--radius`、既定21.2µT)で
方位誤差[度]に直して併記する。
"""
from __future__ import annotations

import argparse
import math
import sys

import numpy as np

LSB_UT = 0.15  # 実測の量子化刻み


def parse_csv(lines) -> np.ndarray:
    """(N,6) [t_s, x, y, z, temp, phase]。status!=0x00・列不足・壊れた行は捨てる。"""
    rows = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        f = ln.split(",")
        if len(f) < 7:
            continue
        try:
            if int(f[1], 16) != 0:
                continue
            rows.append([float(f[0]) / 1000.0, float(f[2]), float(f[3]), float(f[4]),
                         float(f[5]), int(f[6])])
        except ValueError:
            continue
    return np.array(rows, dtype=float).reshape(-1, 6)


def split_windows(d: np.ndarray, skip_s: float) -> list[dict]:
    """phaseが変わるたびに窓を切る。各窓の先頭skip_s秒を捨てた上で中央値・標準偏差を出す。"""
    out = []
    start = 0
    for i in range(1, len(d) + 1):
        if i == len(d) or d[i, 5] != d[start, 5]:
            w = d[start:i]
            keep = w[w[:, 0] >= w[0, 0] + skip_s]
            if len(keep) >= 10:
                out.append({"phase": int(w[0, 5]), "t0": float(w[0, 0]), "n": len(keep),
                            "med": np.median(keep[:, 1:4], axis=0), "std": keep[:, 1:4].std(axis=0)})
            start = i
    return out


def effect(wins: list[dict]) -> dict:
    deltas, idle_std, scan_std, idle_pair = [], [], [], []
    for k, w in enumerate(wins):
        if w["phase"] == 1:
            scan_std.append(w["std"])
            prev = wins[k - 1] if k >= 1 and wins[k - 1]["phase"] == 0 else None
            nxt = wins[k + 1] if k + 1 < len(wins) and wins[k + 1]["phase"] == 0 else None
            if prev is not None and nxt is not None:
                deltas.append(w["med"] - (prev["med"] + nxt["med"]) / 2.0)
                idle_pair.append(nxt["med"] - prev["med"])
        else:
            idle_std.append(w["std"])
    res: dict = {"n_pairs": len(deltas)}
    if not deltas:
        return res
    D = np.array(deltas)
    res["mean"] = D.mean(axis=0)
    res["sem"] = D.std(axis=0, ddof=1) / math.sqrt(len(D)) if len(D) > 1 else np.full(3, np.nan)
    res["idle_drift_sd"] = np.array(idle_pair).std(axis=0, ddof=1) / math.sqrt(2) if len(idle_pair) > 1 else np.full(3, np.nan)
    res["std_idle"] = np.mean(idle_std, axis=0)
    res["std_scan"] = np.mean(scan_std, axis=0)
    return res


def report(res: dict, radius: float) -> str:
    if not res.get("n_pairs"):
        return "解析できる(OFF→スキャン→OFFの)窓の組が無い。取り込みを長くしろ。"
    L = [f"窓の組 {res['n_pairs']} 組(スキャン窓−前後OFF窓の平均)"]
    for i, nm in enumerate("xyz"):
        m, s = res["mean"][i], res["sem"][i]
        sig = (abs(m) > 3 * s) and (abs(m) > LSB_UT) if not math.isnan(s) else False
        ratio = res["std_scan"][i] / max(res["std_idle"][i], 1e-9)
        L.append(f"  {nm}: 差 {m:+.3f} ± {s:.3f} µT ({'有意' if sig else '有意でない'})"
                 f"  窓内標準偏差 OFF {res['std_idle'][i]:.3f} / スキャン {res['std_scan'][i]:.3f} (比{ratio:.2f})")
    h = math.hypot(res["mean"][0], res["mean"][1])
    L.append(f"水平の差ベクトル {h:.3f}µT → 最悪 {math.degrees(h / radius):.2f}° の方位ずれに相当(半径{radius:g}µT)")
    L.append(f"参考: OFF窓どうしの窓中央値のゆらぎ(ドリフト)≒ x={res['idle_drift_sd'][0]:.3f} y={res['idle_drift_sd'][1]:.3f} z={res['idle_drift_sd'][2]:.3f} µT"
             f"、量子化 {LSB_UT}µT")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=420.0)
    ap.add_argument("--save")
    ap.add_argument("--skip", type=float, default=4.0, help="窓の先頭で捨てる秒数（切替直後の過渡）")
    ap.add_argument("--radius", type=float, default=21.2, help="水平半径[µT](方位誤差への換算)")
    args = ap.parse_args()
    if args.csv:
        lines = open(args.csv).readlines()
    else:
        import time

        import serial
        lines = []
        with serial.Serial(args.port, args.baud, timeout=1) as ser:
            end = time.time() + args.seconds
            while time.time() < end:
                ln = ser.readline().decode("utf-8", "replace")
                if ln:
                    lines.append(ln)
        if args.save:
            open(args.save, "w").writelines(lines)
    d = parse_csv(lines)
    if len(d) < 50:
        raise SystemExit(f"有効なサンプルが少ない({len(d)}件)。")
    print(report(effect(split_windows(d, args.skip)), args.radius))
    return 0


if __name__ == "__main__":
    sys.exit(main())
