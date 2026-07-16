"""波形のクイックルック画像(PNG)をサーバ側で描く。

ダッシュボードの canvas 波形描画(dashboard/app.js drawWaveform)のサーバ版。
確定報の Slack 通知に添える簡易プレビュー用。軸ごとに DC(重力等)を引いて0中心で
描くのはダッシュボードと同じ思想（z の重力に縦軸が引っ張られて揺れが潰れるのを防ぐ）。
時刻目盛り(JST)・縦グリッド・onset の縦線もダッシュに合わせて入れる。
"""

from __future__ import annotations

import datetime as dt
import io

import numpy as np
from PIL import Image, ImageDraw

W, H = 720, 320
PAD_L, PAD_R, PAD_T, PAD_B = 46, 16, 20, 26
BG = (255, 255, 255)
GRID = (128, 128, 128)
ZERO = (150, 150, 150)
TEXT = (110, 110, 110)
ONSET = (220, 60, 60)
# ダッシュボードの COLORS（x/y/z）に合わせる
COLORS = {0: (37, 99, 235), 1: (22, 163, 74), 2: (234, 88, 12)}
AXIS_LABEL = {0: "X", 1: "Y", 2: "Z"}
JST = dt.timezone(dt.timedelta(hours=9))


def render_png(gal: np.ndarray, fs: float, start_us: int,
               onset_us: int | None = None) -> bytes:
    """gal:(N,3)[gal] の3軸波形を PNG バイト列にする。"""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    n = gal.shape[0]
    if n < 2:
        d.text((PAD_L, H // 2), "データなし", fill=TEXT)
        return _to_bytes(img)

    # 各軸 DC を引いて0中心に。全軸まとめて値域を決める。
    centered = gal - gal.mean(axis=0, keepdims=True)
    lo, hi = float(centered.min()), float(centered.max())
    if lo == hi:
        lo, hi = lo - 1.0, hi + 1.0
    margin = (hi - lo) * 0.1 or 1.0
    lo -= margin
    hi += margin
    yr = hi - lo

    end_us = start_us + (n - 1) / fs * 1e6
    span_us = end_us - start_us

    def X(i: int) -> float:
        return PAD_L + (i / (n - 1)) * plot_w

    def Xt(us: float) -> float:
        return PAD_L + ((us - start_us) / span_us) * plot_w

    def Y(v: float) -> float:
        return PAD_T + plot_h - ((v - lo) / yr) * plot_h

    # 縦グリッド + 時刻目盛り(JST)
    span_sec = span_us / 1e6
    nticks = max(2, min(6, int(plot_w // 110)))
    for k in range(nticks):
        f = k / (nticks - 1)
        x = PAD_L + f * plot_w
        d.line([(x, PAD_T), (x, PAD_T + plot_h)], fill=(230, 230, 230), width=1)
        label = _fmt_time(start_us + f * span_us, span_sec)
        tw = d.textlength(label)
        tx = x if k == 0 else (x - tw if k == nticks - 1 else x - tw / 2)
        d.text((tx, H - PAD_B + 6), label, fill=TEXT)

    # 0線 + 値域ラベル
    y0 = Y(0.0)
    d.line([(PAD_L, y0), (W - PAD_R, y0)], fill=ZERO, width=1)
    d.text((2, Y(hi) - 6), f"{hi:.2f}", fill=TEXT)
    d.text((2, Y(lo) - 6), f"{lo:.2f}", fill=TEXT)

    # onset の縦線
    if onset_us is not None and start_us <= onset_us <= end_us:
        x = Xt(onset_us)
        d.line([(x, PAD_T), (x, PAD_T + plot_h)], fill=ONSET, width=1)

    # 3軸の折れ線。全点だと重いので画素幅程度に間引く。
    step = max(1, n // (plot_w * 2))
    idx = list(range(0, n, step))
    for ax in (0, 1, 2):
        pts = [(X(i), Y(float(centered[i, ax]))) for i in idx]
        d.line(pts, fill=COLORS[ax], width=1)

    # 凡例
    for k, ax in enumerate((0, 1, 2)):
        d.text((W - PAD_R - 54 + k * 18, PAD_T - 14), AXIS_LABEL[ax], fill=COLORS[ax])

    return _to_bytes(img)


def _fmt_time(us: float, span_sec: float) -> str:
    d = dt.datetime.fromtimestamp(us / 1e6, JST)
    return d.strftime("%H:%M") if span_sec >= 600 else d.strftime("%H:%M:%S")


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
