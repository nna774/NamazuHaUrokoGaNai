"""1イベントの要約（最大震度・初動/終了時刻・水平/垂直ピーク）と3D相対変位図（試作）。

他の地震計bot(「地球」)の投稿に載っていた項目のうち、自前の波形から機械的に出せるものを
出してみる試作。**P/S到達のピッキングはしない**——自動ピッカーは弱い地震で破綻する
（docs/post_hoc_detection.md「検討中の拡張」）ので、3D変位図の窓(--win)は人間が
detectlabの図を見て与える。`detectlab.py`には組み込んでいない。

    python event_summary.py --from "2026-10-29 00:07:30" --to "2026-10-29 00:14:00" --device 2 \\
      --win P "00:08:23" "00:08:27" --win S "00:08:57" "00:09:12" \\
      --out ../docs/log/img/chiba-hokutobu-m5.4-1029-summary-device2.png

- **終了時刻**: 1-10Hz帯の包絡(2秒RMS)が背景RMSの2倍を下回って10秒以上続き始めた時刻。
  計測震度の時系列(60秒FIR)は窓の分だけ尾を引くので終了判定には使わない。
- **垂直軸**: 重力が乗っている軸(静穏時の平均の絶対値が最大の軸)。水平はそれ以外2軸の合成。
  機体の向きは較正していないので、水平2軸(H1/H2)は機体軸のまま方位ではない。
- **3D変位**: 0.5-10Hzのバンドパス加速度を時間積分2回(各回に0.5Hzのハイパス)して窓の平均を引く。
  単位はmm。窓内の軌跡の形を見る用で、絶対値は積分の高域通過の影響を受ける。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta

import numpy as np
from scipy import signal

import detectlab as dl
from jismo.realtime import intensity_timeline

JST = timezone(timedelta(hours=9))
BAND = (1.0, 10.0)
STA_S, LTA_S, THR = 0.5, 30.0, 4.0
END_FACTOR, END_HOLD_S = 2.0, 10.0


def hms(t_us: float) -> str:
    return f"{datetime.fromtimestamp(t_us / 1e6, JST):%H:%M:%S.%f}"[:-4]


def parse_time(s: str, day: datetime) -> int:
    """'YYYY-MM-DD HH:MM[:SS]' か 'HH:MM:SS'(dayの日付を使う) をepoch µsにする。"""
    if len(s) <= 8:
        h, m, sec = (int(x) for x in (s.split(":") + ["0"])[:3])
        return int(day.replace(hour=h, minute=m, second=sec, microsecond=0).timestamp() * 1e6)
    return dl.at_to_us(s)


def gravity_axis(data: np.ndarray, fs: float, quiet_s: float = 30.0) -> int:
    n = int(quiet_s * fs)
    return int(np.argmax(np.abs(data[:n].mean(axis=0))))


def envelope(band: np.ndarray, fs: float, win_s: float = 2.0) -> np.ndarray:
    p = (band ** 2).sum(axis=1)
    w = max(1, int(win_s * fs))
    k = np.ones(w) / w
    return np.sqrt(np.convolve(p, k, mode="same"))


def find_end(env: np.ndarray, fs: float, onset_i: int, bg: float) -> int | None:
    """onset以降で、包絡がbg*END_FACTOR未満でEND_HOLD_S秒続き始める最初の添字。"""
    hold = int(END_HOLD_S * fs)
    low = env < bg * END_FACTOR
    run = 0
    for i in range(onset_i, len(env)):
        run = run + 1 if low[i] else 0
        if run >= hold:
            return i - hold + 1
    return None


def integrate_twice(acc_gal: np.ndarray, fs: float, hp: float = 0.5) -> np.ndarray:
    """加速度[gal=cm/s²] → 変位[mm]。各積分の後に0.5Hzのハイパスでドリフトを落とす。"""
    sos = signal.butter(2, hp, btype="high", fs=fs, output="sos")
    v = signal.sosfiltfilt(sos, np.cumsum(acc_gal, axis=0) / fs, axis=0)
    d = signal.sosfiltfilt(sos, np.cumsum(v, axis=0) / fs, axis=0)
    return d * 10.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--from", dest="t_from", required=True, help="解析区間の開始(JST)")
    ap.add_argument("--to", dest="t_to", required=True, help="解析区間の終了(JST)")
    ap.add_argument("--device", type=int, default=1)
    ap.add_argument("--bucket")
    ap.add_argument("--win", nargs=3, action="append", default=[], metavar=("名前", "開始", "終了"),
                    help="3D変位を描く窓。'HH:MM:SS'(--fromの日付)か完全な時刻。複数指定可")
    ap.add_argument("--out", help="PNGの保存先（省略時は表示のみ=GUIが開く）")
    args = ap.parse_args()

    start_req = dl.at_to_us(args.t_from)
    end_req = dl.at_to_us(args.t_to)
    day = datetime.fromtimestamp(start_req / 1e6, JST)
    data, start_us, fs = dl.load_s3_window(dl.resolve_bucket(args.bucket), end_req,
                                           (end_req - start_req) / 1e6, args.device)
    t = np.arange(len(data)) / fs

    g = gravity_axis(data, fs)
    h_axes = [a for a in range(3) if a != g]
    names = "xyz"
    print(f"# device={args.device}  {hms(start_us)}〜{hms(start_us + len(data) / fs * 1e6)}"
          f"  fs={fs:g}Hz  重力軸={names[g]}（垂直）/ 水平={names[h_axes[0]]},{names[h_axes[1]]}")

    # 最大震度
    it, iv = intensity_timeline(data, fs, 0.5)
    k = int(np.argmax(iv))
    print(f"最大震度 I={iv[k]:.2f}  （{hms(start_us + it[k] * 1e6)}、60秒FIR窓）")

    # 初動・終了
    band, ratio, onsets, _rect, _vec = dl.analyze(data, fs, start_us, BAND, "xyz",
                                                  STA_S, LTA_S, THR, 2.0)
    if not onsets:
        print("初動: 閾値未達（STA/LTA > 4 なし）")
        onset_us = None
    else:
        onset_us = onsets[0]
        onset_i = int(round((onset_us - start_us) / 1e6 * fs))
        env = envelope(band, fs)
        bg = float(np.median(env[max(0, onset_i - int(60 * fs)):max(1, onset_i - int(5 * fs))]))
        end_i = find_end(env, fs, onset_i, bg)
        print(f"初動   {hms(onset_us)}  （STA/LTA 1番目の閾値超過、ピーク比 {ratio.max():.1f}）")
        if end_i is None:
            print("終了   解析区間内に見つからない（区間を伸ばせ）")
        else:
            end_us = start_us + end_i / fs * 1e6
            print(f"終了   {hms(end_us)}  （包絡が背景{bg:.3f}galの{END_FACTOR:g}倍未満で{END_HOLD_S:g}秒継続）")
            print(f"継続   {(end_us - onset_us) / 1e6:.0f}秒")

    # 水平/垂直ピーク（0.5-30Hz、重力DC除去）
    wide = dl.bandpass(data, fs, 0.5, 30.0)
    horiz = np.sqrt((wide[:, h_axes] ** 2).sum(axis=1))
    vert = np.abs(wide[:, g])
    for label, y in (("水平", horiz), ("垂直", vert)):
        j = int(np.argmax(y))
        rel = f"（初動+{(start_us + j / fs * 1e6 - onset_us) / 1e6:.1f}s）" if onset_us else ""
        print(f"ピーク{label} {y[j]:.2f}gal  {hms(start_us + j / fs * 1e6)}{rel}")

    if not args.out and not args.win:
        return 0

    import matplotlib
    if args.out:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    installed = {f.name for f in fm.fontManager.ttflist}
    for jp in ("Hiragino Sans", "Hiragino Kaku Gothic Pro", "YuGothic", "Noto Sans CJK JP", "IPAexGothic"):
        if jp in installed:
            plt.rcParams["font.family"] = jp
            break
    plt.rcParams["axes.unicode_minus"] = False

    disp = integrate_twice(wide[:, [h_axes[0], h_axes[1], g]], fs)
    nwin = max(1, len(args.win))
    fig = plt.figure(figsize=(8 + 4 * nwin, 9))
    gs = fig.add_gridspec(3, 1 + nwin, width_ratios=[2.2] + [1.6] * nwin)
    ref = onset_us if onset_us else start_us
    tt = (start_us + t * 1e6 - ref) / 1e6
    ax = fig.add_subplot(gs[0, 0])
    ax.plot(start_us / 1e6 * 0 + (start_us + it * 1e6 - ref) / 1e6, iv, color="C0")
    ax.set_ylabel("計測震度"); ax.set_title(f"device {args.device}  最大 I={iv[k]:.2f}", loc="left", fontsize=10)
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax)
    ax2.plot(tt, horiz, lw=0.4, color="C4"); ax2.set_ylabel("水平 [gal]")
    ax3 = fig.add_subplot(gs[2, 0], sharex=ax)
    ax3.plot(tt, vert, lw=0.4, color="C2"); ax3.set_ylabel("垂直 [gal]")
    ax3.set_xlabel(f"初動からの経過 [s]（初動={hms(ref)}）" if onset_us else "区間先頭からの経過 [s]")
    for a in (ax, ax2, ax3):
        for _n, w0, w1 in args.win:
            a.axvspan((parse_time(w0, day) - ref) / 1e6, (parse_time(w1, day) - ref) / 1e6,
                      color="C1", alpha=0.15)
    for c, (wname, w0, w1) in enumerate(args.win, start=1):
        i0 = int(round((parse_time(w0, day) - start_us) / 1e6 * fs))
        i1 = int(round((parse_time(w1, day) - start_us) / 1e6 * fs))
        seg = disp[i0:i1] - disp[i0:i1].mean(axis=0)
        a3 = fig.add_subplot(gs[:, c], projection="3d")
        lim = max(0.05, float(np.abs(seg).max()) * 1.1)
        a3.plot(seg[:, 0], seg[:, 1], seg[:, 2], color="C9", lw=1.0)
        a3.plot(seg[:, 0], seg[:, 1], np.full(len(seg), -lim), color="C4", lw=0.7)
        a3.plot(seg[:, 0], np.full(len(seg), lim), seg[:, 2], color="C1", lw=0.7)
        a3.plot(np.full(len(seg), -lim), seg[:, 1], seg[:, 2], color="C2", lw=0.7)
        a3.scatter(*seg[0], color="k", s=14); a3.scatter(*seg[-1], color="r", s=14)
        a3.set_xlim(-lim, lim); a3.set_ylim(-lim, lim); a3.set_zlim(-lim, lim)
        a3.set_xlabel("H1 [mm]"); a3.set_ylabel("H2 [mm]"); a3.set_zlabel("V [mm]")
        a3.set_title(f"{wname}波窓 {w0}〜{w1}\n最大変位 {np.abs(seg).max():.3f}mm", fontsize=10)
        print(f"3D窓 {wname}: {w0}〜{w1}  最大変位 {np.abs(seg).max():.3f}mm  "
              f"範囲 H1 {np.ptp(seg[:, 0]):.3f} / H2 {np.ptp(seg[:, 1]):.3f} / V {np.ptp(seg[:, 2]):.3f} mm")
    fig.tight_layout()
    if args.out:
        fig.savefig(args.out, dpi=110)
        print(f"# saved {args.out}")
    else:
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
