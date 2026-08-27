"""ファームのシリアル出力(`t_us,raw,...`形式)をリアルタイムに波形+FFTで表示する。

`firmware/src/hall_main.cpp`等の机上確認用ブリングアップが吐く`# `始まりの
ヘッダ行以外のCSVを想定。1列目がus単位のタイムスタンプ、2列目が読みたい生値
（3列目以降は無視）であればセンサ非依存で使える——アーム/振り子の叩き試験で
「速いリンギングか、遅い揺れか」を目視確認する用途に作った。

使い方:
    python tools/live_scope.py --port /dev/cu.usbmodem101

ウィンドウを閉じると終了する。サンプルレートはタイムスタンプの中央値から
自動推定するので、ファーム側の`kSampleIntervalUs`を変えても指定し直す必要はない。
"""

from __future__ import annotations

import argparse
import collections
import sys
import threading

import matplotlib
matplotlib.use("MacOSX")
matplotlib.rcParams["font.family"] = "Hiragino Sans"  # 日本語ラベルの文字化け対策(macOS標準)
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np

try:
    import serial  # pyserial
except ImportError:
    serial = None


def despike_median3(x: np.ndarray) -> np.ndarray:
    """3点中央値フィルタ。ESP32のanalogReadに乗る単発ノイズ(前後に対し
    20〜40カウントほど一瞬だけ振れて次のサンプルで戻る)を、本物の(複数
    サンプルにまたがる)揺れを削らずに均す(2026-08-28、実機で確認)。"""
    if len(x) < 3:
        return x
    out = x.copy()
    out[1:-1] = np.median(np.stack([x[:-2], x[1:-1], x[2:]]), axis=0)
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True)
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--window-seconds", type=float, default=2.0,
                   help="波形パネルに表示する直近の秒数(既定2.0秒)")
    p.add_argument("--fft-seconds", type=float, default=4.0,
                   help="FFTに使う直近の秒数、長いほど周波数分解能が上がる(既定4.0秒)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if serial is None:
        print("pyserial 未インストール: pip install pyserial", file=sys.stderr)
        return 1

    # timeoutを付けて専用スレッドでブロッキング読み出しする(下記reader_loop参照)。
    # GUI(matplotlib)のタイマーはウィンドウがバックグラウンドに回ると
    # macOSのApp Nap等でthrottleされ、読み出し頻度が落ちることがある
    # （2026-08-28、ユーザー報告）。読み出しをGUIの描画タイマーから切り離し、
    # 別スレッドで常時読み続けることで、描画が詰まってもシリアル受信自体は
    # 止まらないようにする。
    ser = serial.Serial(args.port, args.baud, timeout=0.2)

    # window-seconds・fft-secondsのうち長い方が収まる固定長リングバッファ。
    # fft-secondsだけを基準にすると、window-secondsをそれより長く指定しても
    # バッファ自体が足りず表示が短いまま頭打ちになる(2026-08-28、実機で確認)。
    # サンプルレートが未確定な起動直後は仮に4kHzを見込んだ長さを確保しておく
    # （実レートが分かり次第、中身は自然に追従する）。
    maxlen = int(max(args.window_seconds, args.fft_seconds) * 4000)
    t_buf: collections.deque[int] = collections.deque(maxlen=maxlen)
    v_buf: collections.deque[float] = collections.deque(maxlen=maxlen)
    line_buf = b""
    buf_lock = threading.Lock()
    stop_event = threading.Event()

    fig, (ax_wave, ax_fft) = plt.subplots(2, 1, figsize=(10, 7))
    wave_line, = ax_wave.plot([], [], lw=1)
    ax_wave.set_xlabel("time [s] (直近ウィンドウ内の相対時刻)")
    ax_wave.set_ylabel("raw")
    ax_wave.set_title("波形(直近 %.1f 秒)" % args.window_seconds)
    ax_wave.grid(alpha=0.3)

    fft_line, = ax_fft.plot([], [], lw=1)
    ax_fft.set_xlabel("frequency [Hz]")
    ax_fft.set_ylabel("|FFT| (log)")
    ax_fft.set_title("FFT (fs推定中...)")
    # 低周波の大きな揺れ(振り子の手動加振等)が線形スケールだと支配的になり、
    # 桁の違う弱い高周波成分(アーム共振のリンギング等)が潰れて見えなくなる
    # ためlogスケールにする(2026-08-28、実機グラフで確認)。
    ax_fft.set_yscale("log")
    ax_fft.grid(alpha=0.3)
    fig.tight_layout()

    def poll_serial() -> None:
        nonlocal line_buf
        line_buf += ser.read(4096)
        while b"\n" in line_buf:
            raw_line, line_buf = line_buf.split(b"\n", 1)
            text = raw_line.decode("ascii", "ignore").strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split(",")
            if len(parts) < 2:
                continue
            try:
                t_us = int(parts[0])
                v = float(parts[1])
            except ValueError:
                continue
            with buf_lock:
                # ボード側が再起動するとmicros()が0近くへ巻き戻る。古い(再起動前の)
                # 大きなタイムスタンプと混在すると差分の中央値からのfs推定が壊れ、
                # 描画がおかしくなったまま復帰しない——バッファを丸ごと初期化して
                # 再起動後のデータだけで新しく組み立て直す。
                if t_buf and t_us < t_buf[-1]:
                    print("[live_scope] タイムスタンプの巻き戻りを検出、"
                          "ボード再起動とみなしてバッファをリセットする", file=sys.stderr)
                    t_buf.clear()
                    v_buf.clear()
                t_buf.append(t_us)
                v_buf.append(v)

    def reader_loop() -> None:
        # GUIの描画タイマーとは独立に、常時シリアルを読み続ける専用スレッド。
        while not stop_event.is_set():
            try:
                poll_serial()
            except serial.SerialException as e:
                # USB瞬断等で一時的に読めなくなってもスレッド自体は止めない。
                print(f"[live_scope] シリアル読み出しエラー(継続): {e}", file=sys.stderr)
                stop_event.wait(0.5)

    reader_thread = threading.Thread(target=reader_loop, daemon=True)
    reader_thread.start()

    def update(_frame):
        with buf_lock:
            if len(t_buf) < 4:
                return wave_line, fft_line
            t = np.array(t_buf, dtype=np.float64)
            v_raw = np.array(v_buf, dtype=np.float64)
        v = despike_median3(v_raw)
        dt_us = np.median(np.diff(t))
        if dt_us <= 0:
            return wave_line, fft_line
        fs = 1e6 / dt_us

        # 波形パネル: 直近window_seconds秒だけ
        win_n = max(4, int(args.window_seconds * fs))
        t_win = t[-win_n:]
        v_win = v[-win_n:]
        t_rel = (t_win - t_win[-1]) / 1e6
        wave_line.set_data(t_rel, v_win)
        ax_wave.set_xlim(t_rel[0], 0)
        pad = max(1.0, (v_win.max() - v_win.min()) * 0.1)
        ax_wave.set_ylim(v_win.min() - pad, v_win.max() + pad)

        # FFTパネル: 直近fft_seconds秒、DCと窓関数のリークを抑えて表示
        fft_n = min(len(v), max(8, int(args.fft_seconds * fs)))
        v_fft = v[-fft_n:]
        v_fft = v_fft - v_fft.mean()
        windowed = v_fft * np.hanning(len(v_fft))
        spec = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(windowed), d=1.0 / fs)
        fft_line.set_data(freqs, spec)
        if len(freqs) > 1:
            ax_fft.set_xlim(0, freqs[-1])
        if spec.size > 1:
            top = spec[1:].max()
            if top > 0:
                # logスケールは0/負を扱えないため、下限はピークから4桁下に置く
                # (弱い高周波成分と、床のノイズレベルの両方が収まる程度の幅)。
                ax_fft.set_ylim(max(top * 1e-4, 1e-9), top * 1.2)
        ax_fft.set_title(f"FFT (fs≈{fs:.0f}Hz, N={fft_n})")

        return wave_line, fft_line

    ani = animation.FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    plt.show()
    stop_event.set()
    reader_thread.join(timeout=1.0)
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
