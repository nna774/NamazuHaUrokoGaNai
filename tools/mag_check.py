"""MLX90393の机上確認ログから、固定の磁気オフセット(ハードアイアン)とドリフトを見る。

`firmware/src/mlx90393_main.cpp`(`pio run -e mlx90393-bringup[-c3] -t upload`)が吐く
`t_ms,status,x_uT,y_uT,z_uT,temp_C` を読む。方位センサとして使う前に、
**センサ近傍の鉄(ヘッダピン等)の磁化がどれだけ乗っているか**を実測するための道具
（[docs/log/2026-10-29-mag-check-tool.md](../docs/log/2026-10-29-mag-check-tool.md)）。

    # シリアルから60秒取りながら解析（--saveでCSVも残す）
    python mag_check.py --port /dev/cu.usbmodem101 --seconds 60 --save cap.csv
    # 取ったCSVを解析し直す／図を出す
    python mag_check.py --csv cap.csv --out mag.png

使い方は2種類:
- **回す**: センサを水平な机の上でゆっくり1〜2周回す(3軸とも振りたいなら色々な向きに)。
  円/球の中心が固定オフセット、半径が地磁気の大きさ。
- **置く**: 動かさずに数分〜数時間置く。中央値の時間変化(µT/時)で磁化の安定性を見る。

回転の網羅度が足りない時は、円/球フィットの結果は出さずに理由を書く。
地磁気の目安(日本の中部〜関東): 全磁力 約45〜50µT、水平成分 約30µT。
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

EARTH_TOTAL_UT = (45.0, 50.0)  # 目安。場所で数µT変わる
EARTH_HORIZ_UT = 30.0


def parse_csv(lines) -> np.ndarray:
    """(N,5)の配列 [t_s, x, y, z, temp] を返す。コメント行・status!=0x00・壊れた行は捨てる。"""
    rows = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        f = ln.split(",")
        if len(f) < 6:
            continue
        try:
            if int(f[1], 16) != 0:
                continue
            rows.append([float(f[0]) / 1000.0, float(f[2]), float(f[3]), float(f[4]), float(f[5])])
        except ValueError:
            continue
    return np.array(rows, dtype=float).reshape(-1, 5)


def fit_sphere(p: np.ndarray) -> tuple[np.ndarray, float, float]:
    """中心c・半径R・残差RMSを最小二乗(線形化)で返す。p は (N,3)。"""
    a = np.c_[2 * p, np.ones(len(p))]
    b = (p ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    c = sol[:3]
    r = float(np.sqrt(max(sol[3] + c @ c, 0.0)))
    resid = np.linalg.norm(p - c, axis=1) - r
    return c, r, float(np.sqrt(np.mean(resid ** 2)))


def fit_circle(p: np.ndarray) -> tuple[np.ndarray, float, float]:
    """(N,2)の円フィット。"""
    a = np.c_[2 * p, np.ones(len(p))]
    b = (p ** 2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    c = sol[:2]
    r = float(np.sqrt(max(sol[2] + c @ c, 0.0)))
    resid = np.linalg.norm(p - c, axis=1) - r
    return c, r, float(np.sqrt(np.mean(resid ** 2)))


def angular_coverage(p2: np.ndarray, c: np.ndarray, bins: int = 36) -> float:
    ang = np.arctan2(p2[:, 1] - c[1], p2[:, 0] - c[0])
    hist, _ = np.histogram(ang, bins=bins, range=(-np.pi, np.pi))
    return float((hist > 0).mean())


def drift_per_hour(t: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    """各軸の線形トレンド[µT/時]。"""
    if len(t) < 2 or t[-1] - t[0] <= 0:
        return np.zeros(3)
    return np.array([np.polyfit(t, xyz[:, i], 1)[0] * 3600.0 for i in range(3)])


def analyze(d: np.ndarray) -> dict:
    t, xyz, temp = d[:, 0], d[:, 1:4], d[:, 4]
    rng = xyz.max(axis=0) - xyz.min(axis=0)
    out: dict = {"n": len(d), "duration_s": float(t[-1] - t[0]), "range": rng,
                 "median": np.median(xyz, axis=0), "std": xyz.std(axis=0),
                 "norm_median": float(np.median(np.linalg.norm(xyz, axis=1))),
                 "temp_median": float(np.median(temp)), "drift_per_h": drift_per_hour(t, xyz)}
    moving = rng.max() > 15.0  # 地磁気ノイズ(数µT)を超えて振れていれば回転データとみなす
    out["moving"] = bool(moving)
    if not moving:
        return out
    if (rng >= 40.0).all():
        c, r, rms = fit_sphere(xyz)
        out["fit"] = {"kind": "sphere", "center": c, "radius": r, "rms": rms,
                      "coverage": None, "note": ""}
    else:
        c2, r, rms = fit_circle(xyz[:, :2])
        cov = angular_coverage(xyz[:, :2], c2)
        note = ""
        if cov < 0.7:
            note = f"水平の周回が足りない(網羅{cov * 100:.0f}%<70%)。もう1周ゆっくり回せ"
        elif (rng[:2] < 20.0).any():
            note = "XYの振れが小さい。水平面内で回せているか確認しろ"
        out["fit"] = {"kind": "circle(XY)", "center": c2, "radius": r, "rms": rms,
                      "coverage": cov, "note": note,
                      "z_range": float(rng[2])}
    return out


def report(res: dict) -> str:
    L = []
    L.append(f"サンプル {res['n']} 件 / {res['duration_s']:.0f}秒  温度中央値 {res['temp_median']:.1f}℃")
    m, s, rg = res["median"], res["std"], res["range"]
    L.append(f"中央値 x={m[0]:+.1f} y={m[1]:+.1f} z={m[2]:+.1f} µT  ノルム {res['norm_median']:.1f}µT")
    L.append(f"振れ幅 x={rg[0]:.1f} y={rg[1]:.1f} z={rg[2]:.1f} µT  標準偏差 x={s[0]:.2f} y={s[1]:.2f} z={s[2]:.2f} µT")
    if not res["moving"]:
        dr = res["drift_per_h"]
        L.append("静置データとして扱う。")
        L.append(f"ドリフト(線形トレンド) x={dr[0]:+.2f} y={dr[1]:+.2f} z={dr[2]:+.2f} µT/時"
                 f"  (測定時間が短いと意味が薄い。数十分以上で見ろ)")
        lo, hi = EARTH_TOTAL_UT
        n = res["norm_median"]
        if n > hi * 1.6:
            L.append(f"ノルム{n:.0f}µTが地磁気の目安({lo:g}〜{hi:g}µT)を大きく超える。"
                     f"固定の磁化(鉄ピン等)が乗っている疑い。回して円の中心を見ろ。")
        return "\n".join(L)
    f = res["fit"]
    c = np.asarray(f["center"])
    L.append(f"フィット: {f['kind']}  半径 {f['radius']:.1f}µT  残差RMS {f['rms']:.2f}µT"
             f"  ({f['rms'] / max(f['radius'], 1e-9) * 100:.1f}%)")
    off = float(np.linalg.norm(c))
    L.append("固定オフセット(中心) " + " ".join(f"{v:+.1f}" for v in c) + f" µT  大きさ {off:.1f}µT")
    if f["kind"] == "sphere":
        lo, hi = EARTH_TOTAL_UT
        L.append(f"半径は地磁気の全磁力に相当する(目安{lo:g}〜{hi:g}µT)。"
                 + ("収まっている。" if lo * 0.8 <= f["radius"] <= hi * 1.2 else "外れている(ソフトアイアン等)。"))
    else:
        L.append(f"半径は水平成分に相当する(目安{EARTH_HORIZ_UT:g}µT前後)。"
                 f"Zの振れ{f['z_range']:.1f}µTは、水平に保てていれば小さい。")
    if f["coverage"] is not None:
        L.append(f"周回の網羅 {f['coverage'] * 100:.0f}%")
    if f["note"]:
        L.append("注意: " + f["note"])
    ratio = off / max(f["radius"], 1e-9)
    verdict = ("小さい。補正で十分引ける" if ratio < 0.3
               else "中程度。補正は要るが使える" if ratio < 1.0
               else "半径より大きい。固定の磁化が支配的。ピンを切る/消磁/別個体を検討")
    L.append(f"オフセット/半径 = {ratio:.2f}  → {verdict}")
    return "\n".join(L)


def plot(d: np.ndarray, res: dict, out: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    installed = {f.name for f in fm.fontManager.ttflist}
    for jp in ("Hiragino Sans", "Hiragino Kaku Gothic Pro", "YuGothic", "Noto Sans CJK JP", "IPAexGothic"):
        if jp in installed:
            plt.rcParams["font.family"] = jp
            break
    plt.rcParams["axes.unicode_minus"] = False

    xyz = d[:, 1:4]
    fig, ax = plt.subplots(2, 2, figsize=(11, 9))
    for a, (i, j, nm) in zip((ax[0, 0], ax[0, 1], ax[1, 0]), ((0, 1, "X-Y"), (0, 2, "X-Z"), (1, 2, "Y-Z"))):
        a.scatter(xyz[:, i], xyz[:, j], s=3)
        a.axhline(0, color="gray", lw=0.5); a.axvline(0, color="gray", lw=0.5)
        a.set_aspect("equal"); a.set_title(f"{nm} [µT]")
    f = res.get("fit")
    if f:
        c = np.asarray(f["center"])
        th = np.linspace(0, 2 * np.pi, 200)
        ax[0, 0].plot(c[0] + f["radius"] * np.cos(th), c[1] + f["radius"] * np.sin(th), "r-", lw=1)
        ax[0, 0].plot(*c[:2], "r+", ms=14)
    ax[1, 1].plot(d[:, 0] - d[0, 0], np.linalg.norm(xyz, axis=1), lw=0.6)
    ax[1, 1].set_xlabel("t [s]"); ax[1, 1].set_title("ノルム [µT]")
    fig.tight_layout()
    fig.savefig(out, dpi=110)


def capture(port: str, baud: int, seconds: float) -> list[str]:
    try:
        import serial
    except ImportError:
        raise SystemExit("pyserial が要る: pip install pyserial")
    lines: list[str] = []
    with serial.Serial(port, baud, timeout=1) as ser:
        end = time.time() + seconds
        while time.time() < end:
            ln = ser.readline().decode("utf-8", "replace")
            if ln:
                lines.append(ln)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="解析するCSV")
    src.add_argument("--port", help="シリアルポート。--secondsだけ取って解析する")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--save", help="--port時に取ったCSVの保存先")
    ap.add_argument("--out", help="図(PNG)の保存先")
    args = ap.parse_args()
    if args.csv:
        with open(args.csv) as fh:
            lines = fh.readlines()
    else:
        print(f"# {args.port} から {args.seconds:g}秒取る。センサを動かしながら待て…", file=sys.stderr)
        lines = capture(args.port, args.baud, args.seconds)
        if args.save:
            with open(args.save, "w") as fh:
                fh.writelines(lines)
    d = parse_csv(lines)
    if len(d) < 20:
        raise SystemExit(f"有効なサンプルが少ない({len(d)}件)。statusが0x00以外・配線・ポートを確認しろ。")
    res = analyze(d)
    print(report(res))
    if args.out:
        plot(d, res, args.out)
        print(f"# saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
