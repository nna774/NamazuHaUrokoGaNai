"""地震検知のコアロジック（純関数）。ローカルでもバックテストできるよう副作用を持たない。

jismo（tools/jismo）の計測震度算出を使う。detect Lambda はこれを呼ぶだけ。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from jismo import jma_fft


# 窓の端から捨てる秒数。FFTフィルタは巡回畳み込みなので、記録の終端と始端が
# 繋がったものとして扱われ、そこに段差があると端がリンギングする。デトレンド
# （jma_fft.detrend）で大半は消えるが、窓の切れ目に本物の過渡が跨いだ場合は残る。
# 窓は WINDOW_SECONDS=120 を 30秒刻み(NAMZ_DETECT_STRIDE_S)で評価するので重なりが厚く、
# 端を数秒捨てても取りこぼさない（次の窓では同じ時刻が内側に来る）。刻みを実効窓長
# （120-2*5=110秒）より粗くすると成り立たなくなるので clamp_stride で切り詰める。
# 詳細は docs/intensity_pitfalls.md。
EDGE_GUARD_SECONDS = 5.0


def amp_for_intensity(intensity: float) -> float:
    """計測震度 I に対応する基準加速度 a0 [gal]。I = 2log10(a0)+0.94 の逆。"""
    return 10.0 ** ((intensity - 0.94) / 2.0)


def core_slice(n: int, fs: float, edge_seconds: float = EDGE_GUARD_SECONDS) -> slice:
    """端を落とした評価区間。短すぎる窓では落とさない（落とすものが無くなるため）。"""
    g = int(edge_seconds * fs)
    return slice(g, n - g) if n > 4 * g else slice(0, n)


def clamp_stride(stride_seconds: float, window_seconds: float) -> float:
    """評価刻み(stride)を実効窓長に収める。0以下なら0（間引きなし）。

    刻みが実効窓長（端を捨てた後の長さ）を超えると、どの窓にも入らない時刻ができて
    取りこぼしになる。設定ミスで検知が穴だらけになるのは避けたいので切り詰める。
    """
    if stride_seconds <= 0:
        return 0.0
    return min(stride_seconds, max(0.0, window_seconds - 2 * EDGE_GUARD_SECONDS))


def crosses_stride(batch_start_us: int, batch_end_us: int, stride_seconds: float) -> bool:
    """このバッチが stride の境界を跨ぐか = 窓の再評価を担当するか。

    detect はバッチ到着ごとに起動するが、窓長より短いバッチでは評価が重複する。
    「stride の境界を跨いだバッチだけが担当」という規則にすると、Lambda 側に前回の
    記憶を持たずに間引ける（絶対時刻の格子で決まるのでデバイス間でも位相が揃う）。
    `batch_len >= stride` なら全バッチが跨ぐので自動的に間引かれなくなる。
    刻みを粗くする代償は確定報の遅れ（最大 stride ぶん）で、取りこぼしではない。
    詳細は docs/design.md。
    """
    if stride_seconds <= 0:
        return True
    stride_us = int(stride_seconds * 1e6)
    return batch_end_us // stride_us > batch_start_us // stride_us


@dataclass
class Detection:
    onset_us: int          # 揺れの立ち上がり時刻
    max_intensity: float   # 窓全体の正式計測震度（FFT版）
    peak_gal: float        # フィルタ後合成加速度のピーク
    a0: float


def analyze(gal: np.ndarray, fs: float, window_start_us: int,
            threshold: float = 0.5, hold_seconds: float = 2.0) -> Detection | None:
    """窓内に「閾値以上が hold_seconds 継続する揺れ」があれば Detection を返す。

    生活振動（<0.5秒の単発スパイク）は継続時間条件で自然に落ちる。
    """
    if gal.shape[0] < int(fs * hold_seconds):
        return None

    comp = jma_fft.filtered_composite(gal[:, 0], gal[:, 1], gal[:, 2], fs)
    core = core_slice(comp.size, fs)
    comp = comp[core]
    a_th = amp_for_intensity(threshold)
    above = comp >= a_th

    # above が hold_n 連続する最初の位置を探す
    hold_n = int(fs * hold_seconds)
    onset_idx = _first_sustained_run(above, hold_n)
    if onset_idx is None:
        return None

    res = jma_fft.intensity_from_composite(comp, fs)
    onset_us = int(window_start_us + (core.start + onset_idx) / fs * 1e6)
    return Detection(onset_us=onset_us, max_intensity=res.intensity,
                     peak_gal=res.peak_gal, a0=res.a0)


def _first_sustained_run(mask: np.ndarray, min_len: int) -> int | None:
    """True が min_len 以上連続する最初の開始インデックスを返す。"""
    run = 0
    for i, v in enumerate(mask):
        if v:
            run += 1
            if run >= min_len:
                return i - min_len + 1
        else:
            run = 0
    return None
