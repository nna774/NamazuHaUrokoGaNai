"""波形のクイックルック画像(PNG)をサーバ側で描く。

ダッシュボードの canvas 波形描画(dashboard/app.js drawWaveform)のサーバ版。
確定報の Slack 通知に添える簡易プレビュー用。軸ごとに DC(重力等)を引いて0中心で
描くのはダッシュボードと同じ思想（z の重力に縦軸が引っ張られて揺れが潰れるのを防ぐ）。
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

W, H = 720, 320
PAD = 36
BG = (255, 255, 255)
GRID = (210, 210, 210)
ZERO = (150, 150, 150)
TEXT = (110, 110, 110)
ONSET = (220, 60, 60)
# ダッシュボードの COLORS（x/y/z）に合わせる
COLORS = {0: (37, 99, 235), 1: (22, 163, 74), 2: (234, 88, 12)}
AXIS_LABEL = {0: "X", 1: "Y", 2: "Z"}


def render_png(gal: np.ndarray, fs: float, start_us: int,
               onset_us: int | None = None) -> bytes:
    """gal:(N,3)[gal] の3軸波形を PNG バイト列にする。"""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    plot_w, plot_h = W - PAD * 2, H - PAD * 2

    n = gal.shape[0]
    if n < 2:
        d.text((PAD, H // 2), "データなし", fill=TEXT)
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

    def X(i: int) -> float:
        return PAD + (i / (n - 1)) * plot_w

    def Y(v: float) -> float:
        return PAD + plot_h - ((v - lo) / yr) * plot_h

    # 0線
    y0 = Y(0.0)
    d.line([(PAD, y0), (W - PAD, y0)], fill=ZERO, width=1)
    d.text((2, Y(hi) - 6), f"{hi:.2f}", fill=TEXT)
    d.text((2, Y(lo) - 6), f"{lo:.2f}", fill=TEXT)

    # onset の縦線
    if onset_us is not None and n > 1:
        end_us = start_us + (n - 1) / fs * 1e6
        if start_us <= onset_us <= end_us:
            fx = (onset_us - start_us) / (end_us - start_us)
            x = PAD + fx * plot_w
            d.line([(x, PAD), (x, PAD + plot_h)], fill=ONSET, width=1)

    # 3軸の折れ線。全点だと重いので画素幅程度に間引く。
    step = max(1, n // (plot_w * 2))
    idx = list(range(0, n, step))
    for ax in (0, 1, 2):
        pts = [(X(i), Y(float(centered[i, ax]))) for i in idx]
        d.line(pts, fill=COLORS[ax], width=1)

    # 凡例
    for k, ax in enumerate((0, 1, 2)):
        d.text((W - PAD - 60 + k * 20, PAD - 14), AXIS_LABEL[ax], fill=COLORS[ax])

    return _to_bytes(img)


def _to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
