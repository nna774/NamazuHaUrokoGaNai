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

    ser = serial.Serial(args.port, args.baud, timeout=0)

    # fft-secondsぶんのサンプルを保持する固定長リングバッファ。
    # サンプルレートが未確定な起動直後は仮に4kHzを見込んだ長さを確保しておく
    # （実レートが分かり次第、中身は自然に追従する）。
    maxlen = int(args.fft_seconds * 4000)
    t_buf: collections.deque[int] = collections.deque(maxlen=maxlen)
    v_buf: collections.deque[float] = collections.deque(maxlen=maxlen)
    line_buf = b""

    fig, (ax_wave, ax_fft) = plt.subplots(2, 1, figsize=(10, 7))
    wave_line, = ax_wave.plot([], [], lw=1)
    ax_wave.set_xlabel("time [s] (直近ウィンドウ内の相対時刻)")
    ax_wave.set_ylabel("raw")
    ax_wave.set_title("波形(直近 %.1f 秒)" % args.window_seconds)
    ax_wave.grid(alpha=0.3)

    fft_line, = ax_fft.plot([], [], lw=1)
    ax_fft.set_xlabel("frequency [Hz]")
    ax_fft.set_ylabel("|FFT|")
    ax_fft.set_title("FFT (fs推定中...)")
    ax_fft.grid(alpha=0.3)
    fig.tight_layout()

    def poll_serial() -> None:
        nonlocal line_buf
        line_buf += ser.read(ser.in_waiting or 1)
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
            t_buf.append(t_us)
            v_buf.append(v)

    def update(_frame):
        poll_serial()
        if len(t_buf) < 4:
            return wave_line, fft_line

        t = np.array(t_buf, dtype=np.float64)
        v = np.array(v_buf, dtype=np.float64)
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
            ax_fft.set_ylim(0, spec[1:].max() * 1.2 + 1e-9)
        ax_fft.set_title(f"FFT (fs≈{fs:.0f}Hz, N={fft_n})")

        return wave_line, fft_line

    ani = animation.FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    plt.show()
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
