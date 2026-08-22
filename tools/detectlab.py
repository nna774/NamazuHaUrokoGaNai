"""ノイズに埋もれた小さな地震を炙り出すオフライン解析ビュー。

時間波形1本では環境ノイズ(足音・ファン・交通)のRMSに埋もれて見えない過渡を、
- バンドパス後の波形
- スペクトログラム(時間×周波数)
- STA/LTA比(短期/長期エネルギー比。地震観測網のトリガの原理)
- 3軸直線性(粒子運動の偏光。地震の実体波は直線偏光、ランダムノイズは等方)
の4視点で可視化し、立ち上がり候補時刻を出力する。

さらに --eew に震源諸元(緯度,経度,深さ,発生時刻)を渡すと、P波・S波の到達予測
窓を全パネルに重ね描きし、その窓の SNR と直線性を数値で出す。「その時刻の揺れが
本当に地震か(到達時刻と偏光が合うか)」の答え合わせに使う。

データ源はS3の生バッチ(フルレート)。api の /event・/recent は MAX_POINTS 超で
エンベロープに間引かれてスペクトル解析に使えないので、raw/ を直読みする。

    # 20:53 から後ろ3分(既定)・前3分(--lead-min既定)をS3から取って解析
    python detectlab.py --at "2026-07-24 20:53" --minutes 3 --out /tmp/2053.png
    # コーダ/後続波まで追いたい時は後ろだけ伸ばす（前を無駄に伸ばしても益がない）
    python detectlab.py --at "2026-07-24 20:53" --minutes 8 --out /tmp/2053.png
    # イベントID指定
    python detectlab.py --event 0001-59462454
    # 手元のキャプチャ/合成CSVで
    python detectlab.py --csv cap.csv --band 1 8 --thr 3
    # 緊急地震速報/震源で答え合わせ(福島県沖 深さ60km 20:52:59発生)
    python detectlab.py --at "2026-07-24 20:53" --minutes 10 --band 0.3 1.5 \
        --eew "37.7,141.7,60,2026-07-24 20:52:59" --out /tmp/2053.png
    # 2機重ね描き（方位較正なしで比較できる回転不変量＝STA/LTA・直線性のみ）
    python detectlab.py --at "2026-08-08 03:41:32" --device 1 2 \
        --eew "36.7,140.6,10,2026-08-08 03:41:32" --out /tmp/overlay.png
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy import signal

JST = ZoneInfo("Asia/Tokyo")

# 到達予測に使う地震波速度の範囲 [km/s]。(速い端, 遅い端) を到達"窓"の両端にする。
# P は地殻内(~6)〜Pn(~7.8)、S は ~3.5〜4.5 のばらつきを幅として表現。
P_VEL_RANGE = (7.8, 6.0)
S_VEL_RANGE = (4.5, 3.5)
# センサ設置点の概略座標(町レベル)。--station / 環境変数 NAMZ_STATION_LATLON で上書き可。
DEFAULT_STATION = (36.936, 138.815)  # 新潟県湯沢町

# lambda/common を再利用してS3の raw/・events/ を直読みする。
# detect Lambda が tools/jismo を共有するのと同じクロス参照の思想（逆向き）。
_LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda"
if str(_LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(_LAMBDA_DIR))


# ---- データ取得 ---------------------------------------------------------

def load_csv(path: str) -> tuple[np.ndarray, int, float]:
    """t_us,x_gal,y_gal,z_gal のCSVを読み (gal[N,3], start_us, fs) を返す。"""
    f = sys.stdin if path == "-" else open(path)
    with f:
        f.readline()  # skip header
        rows = [line.split(",") for line in f if line.strip()]
    arr = np.array(rows, dtype=float)
    t_us = arr[:, 0]
    fs = 1.0 / (np.median(np.diff(t_us)) / 1e6) if len(t_us) > 1 else 100.0
    start_us = int(t_us[0]) if len(t_us) else 0
    return arr[:, 1:4], start_us, fs


def resolve_bucket(explicit: str | None) -> str:
    """rawバケット名を --bucket / 環境変数 / terraform output の順で解決。"""
    if explicit:
        return explicit
    env = os.environ.get("NAMZ_RAW_BUCKET") or os.environ.get("NAMZ_DATA_BUCKET")
    if env:
        return env
    tf = Path(__file__).resolve().parent.parent / "terraform"
    try:
        out = subprocess.run(
            ["terraform", "output", "-raw", "data_bucket"],
            cwd=tf, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "rawバケットを解決できない。--bucket か NAMZ_RAW_BUCKET を指定しろ。"
            f" (terraform output も失敗: {exc})"
        )


def _s3_client(use_cache: bool):
    """band/threshold/windowを変えながら同じ区間を何度も読み直す解析なので、既定で
    `s3cache`(tools/README.md「S3キャッシュ」参照)を使う。`--no-cache`で生のboto3に戻せる。"""
    import awsenv
    awsenv.ensure_region()
    if not use_cache:
        import boto3
        return boto3.client("s3")
    import s3cache
    return s3cache.cached_client()


def load_s3_window(bucket: str, end_us: int, seconds: float,
                   device_id: int, use_cache: bool = True) -> tuple[np.ndarray, int, float]:
    from common import store  # 遅延import。CSV経路ではboto3/AWSに触れない。

    return store.load_window(_s3_client(use_cache), bucket, end_us, seconds, device_id)


def load_s3_event(bucket: str, eid: str, use_cache: bool = True) -> tuple[np.ndarray, int, float]:
    from common import store

    return store.load_event(_s3_client(use_cache), bucket, eid)


# ---- 信号処理 -----------------------------------------------------------

def bandpass(data: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    """ゼロ位相バンドパス(4次Butterworth)。data (N,3) を各軸に適用。"""
    ny = fs / 2.0
    hi = min(hi, ny * 0.99)
    lo = max(lo, 1e-3)
    sos = signal.butter(4, [lo, hi], btype="band", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, data, axis=0)


def sta_lta(cf: np.ndarray, fs: float, sta_s: float, lta_s: float) -> np.ndarray:
    """特性関数 cf(>=0) の STA/LTA 比。末尾移動平均。LTAが溜まる前は0。"""
    n = len(cf)
    nsta = max(1, int(round(sta_s * fs)))
    nlta = max(nsta + 1, int(round(lta_s * fs)))
    csum = np.concatenate([[0.0], np.cumsum(cf)])
    idx = np.arange(n)

    def trailing_mean(win: int) -> np.ndarray:
        lo = np.maximum(0, idx + 1 - win)
        return (csum[idx + 1] - csum[lo]) / (idx + 1 - lo)

    ratio = trailing_mean(nsta) / np.maximum(trailing_mean(nlta), 1e-12)
    ratio[: min(nlta, n)] = 0.0  # LTA窓が埋まるまでは無効
    return ratio


def rolling_correlation(a: np.ndarray, b: np.ndarray, fs: float, win_s: float) -> np.ndarray:
    """同じ時間軸に揃えた2系列の移動相関係数(末尾窓、Pearson)。

    sta_lta と同じ累積和トリックで窓内の sum/sumsq/sumprod を出し、そこから
    相関係数を計算する（ループでの逐次計算より軽い）。窓が埋まるまではnan。
    """
    n = len(a)
    w = max(2, int(round(win_s * fs)))
    csum = np.concatenate([[0.0], np.cumsum(np.ones(n))])
    idx = np.arange(n)
    lo = np.maximum(0, idx + 1 - w)
    cnt = csum[idx + 1] - csum[lo]

    def trailing_sum(x: np.ndarray) -> np.ndarray:
        c = np.concatenate([[0.0], np.cumsum(x)])
        return c[idx + 1] - c[lo]

    sa, sb = trailing_sum(a), trailing_sum(b)
    saa, sbb, sab = trailing_sum(a * a), trailing_sum(b * b), trailing_sum(a * b)
    num = cnt * sab - sa * sb
    den = np.sqrt(np.maximum(cnt * saa - sa ** 2, 0.0) * np.maximum(cnt * sbb - sb ** 2, 0.0))
    corr = np.divide(num, den, out=np.full(n, np.nan), where=den > 1e-12)
    corr[: min(w, n)] = np.nan
    return corr


def align_pair(t_a: np.ndarray, y_a: np.ndarray, t_b: np.ndarray, y_b: np.ndarray,
              fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2機ぶんの(時刻[s], 値)系列を、重なっている区間だけ共通のfs時間軸に補間する。

    起点(start_us)は機体ごとに数十ms単位でズレる（バッチ境界が同期していない）ので、
    素の配列同士を突き合わせるとサンプルが噛み合わない。線形補間で揃える。
    """
    t0, t1 = max(t_a[0], t_b[0]), min(t_a[-1], t_b[-1])
    if t1 <= t0:
        return np.array([]), np.array([]), np.array([])
    t = np.arange(t0, t1, 1.0 / fs)
    return t, np.interp(t, t_a, y_a), np.interp(t, t_b, y_b)


def detect_onsets(ratio: np.ndarray, fs: float, start_us: int, thr: float) -> list[int]:
    """比が閾値を下から上へ跨いだ立ち上がり時刻(epoch µs)を返す。"""
    above = ratio >= thr
    if len(above) < 2:
        return []
    rising = np.where((~above[:-1]) & (above[1:]))[0] + 1
    return [start_us + int(round(i / fs * 1e6)) for i in rising]


def rectilinearity(band: np.ndarray, fs: float, win_s: float) -> np.ndarray:
    """粒子運動の直線性(0..1)を移動窓の共分散行列の固有値から算出。2軸/3軸対応。

    地震の実体波(特にP波)は震源方向に沿った直線偏光 → 最大固有値に集中して1に近づく。
    ランダムな環境ノイズは等方的で固有値が拮抗 → 0に近づく。
    rect = 1 - mean(小さい固有値) / 最大固有値。
    """
    n, k = band.shape
    w = max(3, int(round(win_s * fs)))
    b = band - band.mean(axis=0)
    kern = np.ones(w) / w

    def ma(x: np.ndarray) -> np.ndarray:
        return np.convolve(x, kern, mode="same")

    cov = np.empty((n, k, k))
    for i in range(k):
        for j in range(i, k):
            c = ma(b[:, i] * b[:, j])
            cov[:, i, j] = c
            cov[:, j, i] = c
    ev = np.linalg.eigvalsh(cov)  # 昇順: ev[:,0] <= ... <= ev[:,-1]
    largest = np.maximum(ev[:, -1], 1e-20)
    smaller_mean = ev[:, :-1].mean(axis=1)
    return np.clip(1.0 - smaller_mean / largest, 0.0, 1.0)


# ---- 震源ジオメトリ・到達予測 -------------------------------------------

def hypocentral_km(eq_lat, eq_lon, depth_km, st_lat, st_lon) -> tuple[float, float]:
    """観測点から震源までの距離[km]と震央距離[km]を平面近似で返す。"""
    dlat = (eq_lat - st_lat) * 111.0
    dlon = (eq_lon - st_lon) * 111.0 * math.cos(math.radians((eq_lat + st_lat) / 2))
    epi = math.hypot(dlat, dlon)
    return math.hypot(epi, depth_km), epi


def arrival_window(dist_km: float, origin_us: int, vrange: tuple[float, float]) -> tuple[int, int]:
    """速度範囲(速い端,遅い端)から到達予測窓(早い端us, 遅い端us)を返す。"""
    vmax, vmin = vrange
    return (origin_us + int(dist_km / vmax * 1e6),
            origin_us + int(dist_km / vmin * 1e6))


def parse_station(s: str | None) -> tuple[float, float]:
    src = s or os.environ.get("NAMZ_STATION_LATLON")
    if not src:
        return DEFAULT_STATION
    try:
        lat, lon = (float(x) for x in src.split(","))
        return lat, lon
    except Exception:
        raise SystemExit('--station は "lat,lon" 形式で指定しろ 例: "36.936,138.815"')


def parse_eew(s: str) -> tuple[float, float, float, int]:
    """"lat,lon,depth_km,YYYY-MM-DD HH:MM:SS"(JST発生時刻) をパース。"""
    parts = [x.strip() for x in s.split(",")]
    if len(parts) != 4:
        raise SystemExit(
            '--eew は "緯度,経度,深さkm,YYYY-MM-DD HH:MM:SS"(JST発生時刻) で指定しろ\n'
            '  例: "37.7,141.7,60,2026-07-24 20:52:59"'
        )
    return float(parts[0]), float(parts[1]), float(parts[2]), at_to_us(parts[3])


def window_report(vec: np.ndarray, rect: np.ndarray, fs: float, start_us: int,
                  a_us: int, b_us: int, bg_rms: float) -> tuple[float, float, float] | None:
    """[a,b] 窓の RMS・背景比SNR・エネルギー重み付き直線性を返す。"""
    i0 = max(0, int(round((a_us - start_us) / 1e6 * fs)))
    i1 = min(len(vec), int(round((b_us - start_us) / 1e6 * fs)))
    if i1 <= i0:
        return None
    e = vec[i0:i1] ** 2
    rms = float(np.sqrt(e.mean()))
    snr = rms / bg_rms if bg_rms > 0 else float("nan")
    wrect = float((rect[i0:i1] * e).sum() / max(e.sum(), 1e-20))
    return rms, snr, wrect


def analyze(data: np.ndarray, fs: float, start_us: int, band_range: tuple[float, float],
           axes: str, sta_s: float, lta_s: float, thr: float, rect_win: float):
    """バンドパス・STA/LTA・直線性をまとめて計算する（単一/重ね描き両モード共通）。

    STA/LTA・直線性はどちらも振幅二乗和・共分散固有値という回転不変量から出る
    （docs/device_overlay.md）。方位較正が無くても機体間でそのまま比較できる。
    """
    lo, hi = band_range
    band = bandpass(data, fs, lo, hi)
    nax = 2 if axes == "xy" else 3  # xy=水平のみ / xyz=3軸
    bsel = band[:, :nax]
    cf = (bsel ** 2).sum(axis=1)
    ratio = sta_lta(cf, fs, sta_s, lta_s)
    onsets = detect_onsets(ratio, fs, start_us, thr)
    rect = rectilinearity(bsel, fs, rect_win)
    vec = np.sqrt(cf)
    return band, ratio, onsets, rect, vec


# ---- 出力 ---------------------------------------------------------------

def dump_csv(path: str, data: np.ndarray, start_us: int, fs: float) -> None:
    n = data.shape[0]
    ts = start_us + np.round(np.arange(n) * 1e6 / fs).astype(np.int64)
    with open(path, "w") as f:
        f.write("t_us,x_gal,y_gal,z_gal\n")
        for i in range(n):
            f.write(f"{ts[i]},{data[i, 0]:.5f},{data[i, 1]:.5f},{data[i, 2]:.5f}\n")
    print(f"# dumped {path} ({n} samples)")


def plot(data, band, fs, start_us, ratio, thr, onsets, band_lo, band_hi,
         rect, arrivals, out, show, vec=None, axes_label="xyz", device_id=None):
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    # 日本語ラベルが豆腐にならないよう、環境にある和文フォントを優先。無ければ既定。
    installed = {f.name for f in fm.fontManager.ttflist}
    for jp in ("Hiragino Sans", "Hiragino Kaku Gothic Pro", "YuGothic",
               "Noto Sans CJK JP", "IPAexGothic"):
        if jp in installed:
            plt.rcParams["font.family"] = jp
            break
    plt.rcParams["axes.unicode_minus"] = False

    n = data.shape[0]
    t = np.arange(n) / fs
    fig, axs = plt.subplots(5, 1, figsize=(12, 12), sharex=True)

    shown = "xy" if axes_label == "xy" else "xyz"  # 解析に使う軸だけ描く
    raw_ac = data - data.mean(axis=0)  # 重力DCを除いて交流成分だけ見る
    for i, ax in enumerate(shown):
        axs[0].plot(t, raw_ac[:, i], lw=0.4, label=ax)
    axs[0].set_ylabel("raw-DC [gal]")
    axs[0].legend(loc="upper right", ncol=3, fontsize=8)
    axs[0].set_title("生波形（重力DC除去。ここでは埋もれて見えない）", fontsize=9, loc="left")

    for i, ax in enumerate(shown):
        axs[1].plot(t, band[:, i], lw=0.4, label=ax)
    axs[1].set_ylabel(f"BP {band_lo:g}-{band_hi:g}Hz [gal]")
    axs[1].set_title("バンドパス後（過渡が浮き上がる）", fontsize=9, loc="left")

    if vec is None:
        vec = np.sqrt((band ** 2).sum(axis=1))
    nper = int(min(256, n))
    if nper >= 8:
        f_s, t_s, sxx = signal.spectrogram(
            vec, fs=fs, nperseg=nper, noverlap=(nper * 7) // 8
        )
        axs[2].pcolormesh(t_s, f_s, 10 * np.log10(sxx + 1e-12), shading="gouraud")
        axs[2].set_ylim(0, min(30, fs / 2))
    axs[2].set_ylabel("freq [Hz]")
    axs[2].set_title("スペクトログラム（過渡が縦のエネルギー筋）", fontsize=9, loc="left")

    axs[3].plot(t, ratio, lw=0.6, color="C3")
    axs[3].axhline(thr, ls="--", color="k", lw=0.8)
    axs[3].set_ylabel("STA/LTA")
    axs[3].set_title(f"STA/LTA比（閾値 {thr:g} 超で検出）", fontsize=9, loc="left")

    axs[4].plot(t, rect, lw=0.6, color="C2")
    axs[4].axhline(0.6, ls=":", color="k", lw=0.8)
    axs[4].set_ylim(0, 1)
    axs[4].set_ylabel("直線性")
    axs[4].set_xlabel("t [s] （窓先頭からの経過）")
    rect_axes = "水平2軸" if axes_label == "xy" else "3軸"
    axs[4].set_title(f"{rect_axes}直線性（1=直線偏光≒地震の実体波 / 0.5前後=等方ノイズ）",
                     fontsize=9, loc="left")

    # 到達予測窓（Pは青・Sは赤の帯）。全パネルに重ねる。
    for label, e_us, l_us, color in arrivals:
        e = (e_us - start_us) / 1e6
        l = (l_us - start_us) / 1e6
        for a in axs:
            a.axvspan(e, l, color=color, alpha=0.13)
        axs[0].annotate(label, ((e + l) / 2, axs[0].get_ylim()[1] * 0.82),
                        color=color, ha="center", fontsize=9)

    for o in onsets:
        ot = (o - start_us) / 1e6
        for a in axs:
            a.axvline(ot, color="m", lw=0.8, alpha=0.6)

    t0 = datetime.fromtimestamp(start_us / 1e6, JST)
    device_note = f"  device={device_id}" if device_id is not None else ""
    fig.suptitle(f"detectlab  start={t0:%Y-%m-%d %H:%M:%S JST}  fs={fs:.1f}Hz"
                 f"  N={n}  axes={axes_label}{device_note}")
    fig.tight_layout()
    if out:
        fig.savefig(out, dpi=110)
        print(f"# saved {out}")
    if show:
        plt.show()


def plot_overlay(per_device, thr, arrivals, ref_us, out, show, corr_win=2.0):
    """複数デバイスのSTA/LTA・直線性を同一時間軸に重ねて描く。

    生波形やスペクトログラムは軸の向きが機体ごとに違い重ねる意味が無いので出さない
    （docs/device_overlay.md §2）。STA/LTA・直線性は回転不変量なので方位較正なしで
    そのまま比較できる（同§3-c の考え方）。

    ちょうど2機の重ね描きなら、直線性の移動相関（一致度）パネルを追加する。3機以上は
    どの組み合わせを見せるべきか自明でないため付けない。
    """
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    installed = {f.name for f in fm.fontManager.ttflist}
    for jp in ("Hiragino Sans", "Hiragino Kaku Gothic Pro", "YuGothic",
               "Noto Sans CJK JP", "IPAexGothic"):
        if jp in installed:
            plt.rcParams["font.family"] = jp
            break
    plt.rcParams["axes.unicode_minus"] = False

    show_corr = len(per_device) == 2
    nrows = 3 if show_corr else 2
    fig, axs = plt.subplots(nrows, 1, figsize=(12, 6 if nrows == 2 else 8), sharex=True)
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    for i, (device_id, start_us, fs, ratio, rect, onsets) in enumerate(per_device):
        color = colors[i % len(colors)]
        t = (start_us - ref_us) / 1e6 + np.arange(len(ratio)) / fs
        axs[0].plot(t, ratio, lw=0.7, color=color, label=f"device {device_id}")
        axs[1].plot(t, rect, lw=0.7, color=color, label=f"device {device_id}")
        for o in onsets:
            ot = (o - ref_us) / 1e6
            for a in axs:
                a.axvline(ot, color=color, lw=0.8, alpha=0.6, ls="--")

    if show_corr:
        (dev_a, start_a, fs_a, _, rect_a, _), (dev_b, start_b, fs_b, _, rect_b, _) = per_device
        t_a = (start_a - ref_us) / 1e6 + np.arange(len(rect_a)) / fs_a
        t_b = (start_b - ref_us) / 1e6 + np.arange(len(rect_b)) / fs_b
        t_c, ra, rb = align_pair(t_a, rect_a, t_b, rect_b, min(fs_a, fs_b))
        if len(t_c):
            corr = rolling_correlation(ra, rb, min(fs_a, fs_b), corr_win)
            axs[2].plot(t_c, corr, lw=0.8, color="k")
            axs[2].fill_between(t_c, 0, corr, where=corr >= 0.6, color="C2", alpha=0.25,
                               interpolate=True)
        axs[2].axhline(0.6, ls=":", color="k", lw=0.8)
        axs[2].axhline(0, ls="-", color="gray", lw=0.5)
        axs[2].set_ylim(-1, 1)
        axs[2].set_ylabel("直線性の相関")
        axs[2].set_title(f"直線性の一致度（device {dev_a}/{dev_b} 間、窓{corr_win:g}秒の移動Pearson相関。"
                         "地震なら両機とも同時に立つので1に近づく）", fontsize=9, loc="left")

    def sec_to_clock(x):
        return [datetime.fromtimestamp(ref_us / 1e6 + v, JST) for v in x]

    top = axs[0].secondary_xaxis(
        "top",
        functions=(lambda s: s, lambda s: s),
    )
    top.set_xticks(axs[0].get_xticks())
    top.set_xticklabels([dt.strftime("%H:%M:%S") for dt in sec_to_clock(axs[0].get_xticks())],
                        fontsize=8)
    top.set_xlabel("実時刻 [JST]", fontsize=8)

    axs[0].axhline(thr, ls="--", color="k", lw=0.8)
    axs[0].set_ylabel("STA/LTA")
    axs[0].set_title(f"STA/LTA比 重ね描き（閾値 {thr:g} 超で検出。回転不変量なので方位較正なしで比較可）",
                     fontsize=9, loc="left")
    axs[0].legend(loc="upper right", fontsize=8)

    axs[1].axhline(0.6, ls=":", color="k", lw=0.8)
    axs[1].set_ylim(0, 1)
    axs[1].set_ylabel("直線性")
    axs[1].set_title("直線性 重ね描き（1=直線偏光≒地震の実体波 / 0.5前後=等方ノイズ）",
                     fontsize=9, loc="left")
    ref_dt = datetime.fromtimestamp(ref_us / 1e6, JST)
    ref_note = "発生時刻" if arrivals else "先頭デバイス窓頭"
    xlabel = f"t [s]  （{ref_note} {ref_dt:%Y-%m-%d %H:%M:%S} JST からの経過）"
    axs[-1].set_xlabel(xlabel)

    for label, e_us, l_us, color in arrivals:
        e = (e_us - ref_us) / 1e6
        l = (l_us - ref_us) / 1e6
        for a in axs:
            a.axvspan(e, l, color=color, alpha=0.13)
        axs[0].annotate(label, ((e + l) / 2, axs[0].get_ylim()[1] * 0.85),
                        color=color, ha="center", fontsize=9)

    devices_note = ",".join(str(d) for d, *_ in per_device)
    fig.suptitle(f"detectlab overlay  devices={devices_note}  "
                 f"{ref_note}={ref_dt:%Y-%m-%d %H:%M:%S} JST")
    fig.tight_layout()
    if out:
        fig.savefig(out, dpi=110)
        print(f"# saved {out}")
    if show:
        plt.show()


# ---- CLI ----------------------------------------------------------------

def at_to_us(s: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=JST).timestamp() * 1e6)
        except ValueError:
            continue
    raise SystemExit(f"--at をパースできない: {s!r}  例: '2026-07-24 20:53'")


def main() -> int:
    p = argparse.ArgumentParser(
        description="ノイズに埋もれた小地震を炙り出す解析ビュー",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--event", help="イベントID（events/<id>/ を連結）")
    src.add_argument("--at", help="窓の中心時刻(JST) 例 '2026-07-24 20:53'")
    src.add_argument("--at-us", type=int, help="窓の中心時刻(epoch µs)")
    src.add_argument("--csv", help="t_us,x_gal,y_gal,z_gal のCSV（- でstdin）")
    p.add_argument("--minutes", type=float, default=3.0,
                   help="--at より後ろを何分見るか（--at系。既定3）。前側は既定で"
                        "ほぼ見ない（--lead-min参照）。地震のコーダ/後続波を追うには"
                        "これを伸ばす")
    p.add_argument("--lead-min", dest="lead_min", type=float, default=3.0,
                   help="--at より前を何分見るか（既定3）。背景ノイズの目視確認・"
                        "--eew指定時の背景RMS推定（発生-150秒〜-30秒を使う）に要るぶんで、"
                        "むやみに伸ばしても地震の答え合わせには益がない")
    p.add_argument("--band", type=float, nargs=2, default=[1.0, 10.0],
                   metavar=("LO", "HI"), help="バンドパス帯域[Hz]（既定 1 10）")
    p.add_argument("--sta", type=float, default=1.0, help="STA窓[秒]（既定1）")
    p.add_argument("--lta", type=float, default=30.0, help="LTA窓[秒]（既定30）")
    p.add_argument("--thr", type=float, default=4.0, help="STA/LTA検出閾値（既定4）")
    p.add_argument("--rect-win", dest="rect_win", type=float, default=3.0,
                   help="直線性の移動窓[秒]（既定3）")
    p.add_argument("--corr-win", dest="corr_win", type=float, default=2.0,
                   help="2機重ね描き時、直線性の一致度パネルに使う移動相関の窓[秒]（既定2）")
    p.add_argument("--axes", choices=["xyz", "xy"], default="xyz",
                   help="STA/LTA・スペクトログラム・直線性に使う軸。xy=水平のみ"
                        "（z軸の低周波ノイズが大きい時、遠地弱震で有利）")
    p.add_argument("--eew", help='震源で答え合わせ。"緯度,経度,深さkm,発生時刻(JST)" '
                   '例 "37.7,141.7,60,2026-07-24 20:52:59"。P/S到達窓を重ね描き＋SNR/直線性を出す')
    p.add_argument("--station", help='観測点座標 "lat,lon"（既定は NAMZ_STATION_LATLON / 湯沢町）')
    p.add_argument("--device", type=int, nargs="+", default=[1],
                   help="デバイスID（--at 系で必須。既定1）。混ぜて読むと継ぎ目の段差が揺れに"
                        "見えるので個別に読む。2つ以上指定すると重ね描き解析モード"
                        "（--at/--at-us 限定。STA/LTA・直線性という回転不変量だけを重ねるので"
                        "方位較正なしで比較できる）")
    p.add_argument("--bucket", help="rawバケット名（既定は NAMZ_RAW_BUCKET / terraform）")
    p.add_argument("--no-cache", action="store_true",
                   help="S3から毎回取り直す（既定は.s3cache/でget_objectをキャッシュ。"
                        "raw batchは書き込み後不変なので通常は付けなくてよい）")
    p.add_argument("--out", help="図の保存先PNG（無指定なら画面表示）")
    p.add_argument("--dump-csv", dest="dump", help="取得した生窓をCSV保存（再利用用）")
    p.add_argument("--show", action="store_true", help="--out 指定時も画面表示する")
    args = p.parse_args()

    if len(args.device) > 1 and not (args.at or args.at_us):
        raise SystemExit("複数デバイスの重ね描きは --at / --at-us でのみ対応する"
                         "（--event/--csv は単一データ源）")

    # --eew の到達予測窓は全デバイス共通（同一地点に複数機を置く前提。EEWパースも1回でよい）。
    arrivals: list[tuple[str, int, int, str]] = []
    origin_us = None
    if args.eew:
        eq_lat, eq_lon, depth, origin_us = parse_eew(args.eew)
        st_lat, st_lon = parse_station(args.station)
        hypo, epi = hypocentral_km(eq_lat, eq_lon, depth, st_lat, st_lon)
        p_win = arrival_window(hypo, origin_us, P_VEL_RANGE)
        s_win = arrival_window(hypo, origin_us, S_VEL_RANGE)
        arrivals = [("P窓", p_win[0], p_win[1], "C0"), ("S窓", s_win[0], s_win[1], "C3")]
        og = datetime.fromtimestamp(origin_us / 1e6, JST)
        print(f"# EEW: 震央({eq_lat},{eq_lon}) 深さ{depth:g}km  発生 {og:%H:%M:%S}"
              f"  震央距離{epi:.0f}km 震源距離{hypo:.0f}km")

    def report(dev_label: str, fs, start_us, band, ratio, onsets, rect, vec, raw):
        lo, hi = args.band
        n = raw.shape[0]
        raw_rms = np.sqrt(np.mean((raw - raw.mean(axis=0)) ** 2))
        bp_rms = np.sqrt(np.mean(band ** 2))
        t0 = datetime.fromtimestamp(start_us / 1e6, JST)
        prefix = f"# {dev_label} " if dev_label else "# "
        print(f"{prefix}start={t0:%Y-%m-%d %H:%M:%S JST}  fs={fs:.2f}Hz  N={n}"
              f"  ({n / fs:.1f}s)")
        print(f"  band={lo:g}-{hi:g}Hz  axes={args.axes}  raw_rms={raw_rms:.4f}gal"
              f"  bp_rms={bp_rms:.4f}gal  STA/LTA peak={ratio.max():.2f}")
        if onsets:
            for o in onsets:
                ot = datetime.fromtimestamp(o / 1e6, JST)
                oi = min(len(rect) - 1, max(0, int(round((o - start_us) / 1e6 * fs))))
                print(f"    onset候補: {ot:%Y-%m-%d %H:%M:%S.%f} JST"
                      f"  (t+{(o - start_us) / 1e6:.1f}s)  直線性={rect[oi]:.2f}")
        else:
            print(f"    onset候補なし（閾値 {args.thr:g} 未達）。"
                  "--thr を下げる/--band を変えると拾えることも。")
        if not args.eew:
            return
        bg = window_report(vec, rect, fs, start_us,
                           origin_us - 150_000_000, origin_us - 30_000_000, 1.0)
        bg_rms = bg[0] if bg else float(np.sqrt(np.median(vec ** 2)))
        print(f"    背景RMS={bg_rms:.4f}gal")
        for label, e_us, l_us, _ in arrivals:
            ea = datetime.fromtimestamp(e_us / 1e6, JST)
            la = datetime.fromtimestamp(l_us / 1e6, JST)
            r = window_report(vec, rect, fs, start_us, e_us, l_us, bg_rms)
            if r:
                _, snr, wrect = r
                verdict = "地震らしい" if (snr >= 1.5 and wrect >= 0.6) else \
                          "微妙(ノイズと分離できず)" if snr < 1.3 else "要検討"
                print(f"    {label} {ea:%H:%M:%S}-{la:%H:%M:%S}  "
                      f"SNR={snr:.2f}  直線性={wrect:.2f}  → {verdict}")
            else:
                print(f"    {label} {ea:%H:%M:%S}-{la:%H:%M:%S}  （窓が解析範囲外）")

    if args.csv:
        data, start_us, fs = load_csv(args.csv)
        device_id = None  # CSVは任意データなので--deviceの既定値は意味を持たない
    elif args.event:
        data, start_us, fs = load_s3_event(resolve_bucket(args.bucket), args.event,
                                          use_cache=not args.no_cache)
        device_id = int(args.event.split("-", 1)[0])  # event_id先頭4桁=device
    else:
        device_id = args.device[0]
        center = at_to_us(args.at) if args.at else args.at_us
        after_s = args.minutes * 60.0
        lead_s = args.lead_min * 60.0
        seconds = after_s + lead_s
        end_us = int(center + after_s * 1e6)
        planned_start_us = center - int(lead_s * 1e6)
        if origin_us is not None and planned_start_us > origin_us - 150_000_000:
            print(f"# 警告: --lead-min={args.lead_min:g}分では--eewの背景RMS推定"
                  "（発生-150秒〜-30秒）に届かない。背景がイベント自体で汚染され"
                  "SNRが不正確になる。--lead-minを増やすか--atを発生時刻寄りにしろ",
                  file=sys.stderr)

        if len(args.device) > 1:
            # 重ね描き: デバイスごとに個別読み込み・個別解析（混ぜると継ぎ目が揺れに見える）。
            per_device = []
            bucket = resolve_bucket(args.bucket)
            for dev in args.device:
                d_data, d_start, d_fs = load_s3_window(bucket, end_us, seconds, dev,
                                                       use_cache=not args.no_cache)
                if d_data.shape[0] == 0:
                    raise SystemExit(f"device {dev}: 波形が空。時刻・データ保持期間を確認しろ。")
                d_band, d_ratio, d_onsets, d_rect, d_vec = analyze(
                    d_data, d_fs, d_start, args.band, args.axes,
                    args.sta, args.lta, args.thr, args.rect_win)
                report(f"device={dev}", d_fs, d_start, d_band, d_ratio, d_onsets,
                       d_rect, d_vec, d_data)
                if args.dump:
                    stem, dot, ext = args.dump.rpartition(".")
                    dump_csv(f"{stem}.dev{dev}.{ext}" if dot else f"{args.dump}.dev{dev}",
                             d_data, d_start, d_fs)
                per_device.append((dev, d_start, d_fs, d_ratio, d_rect, d_onsets))
            ref_us = origin_us if origin_us is not None else min(p[1] for p in per_device)
            plot_overlay(per_device, args.thr, arrivals, ref_us, args.out,
                        show=args.show or not args.out, corr_win=args.corr_win)
            return 0

        data, start_us, fs = load_s3_window(resolve_bucket(args.bucket), end_us, seconds,
                                            device_id, use_cache=not args.no_cache)

    n = data.shape[0]
    if n == 0:
        raise SystemExit("波形が空。時刻・バケット・データ保持期間を確認しろ。")

    band, ratio, onsets, rect, vec = analyze(
        data, fs, start_us, args.band, args.axes, args.sta, args.lta, args.thr, args.rect_win)
    report("", fs, start_us, band, ratio, onsets, rect, vec, data)

    if args.dump:
        dump_csv(args.dump, data, start_us, fs)

    lo, hi = args.band
    plot(data, band, fs, start_us, ratio, args.thr, onsets, lo, hi,
         rect, arrivals, args.out, show=args.show or not args.out,
         vec=vec, axes_label=args.axes, device_id=device_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
