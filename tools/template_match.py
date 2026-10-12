"""同地域の検出済み地震をテンプレートにした、事後解析の補助判定（試作）。

テンプレート（既に検出できた地震の波形）と対象の発生分付近を3軸の正規化相互相関(NCC)で
突き合わせ、**位相ランダム化テンプレート**との比（z値）で有意性を見る。背景ノイズの分布だけと
比べると、別地域の地震でも「地震らしい帯域のエネルギー」に反応して立ってしまうため、
同じ振幅スペクトルで波形だけ壊した偽テンプレートを対照にする。

使いどころ・限界は docs/post_hoc_detection.md「検討中の拡張」と
docs/log/2026-10-08-template-matching-trial.md を読むこと。**感度が低く（同震央の他の地震は
拾えなかった）、単独で判定は変えない。** `detectlab.py`には組み込んでいない。

    python template_match.py --template-at "2026-10-08 04:14:22" --template-len 80 \\
      --target "2026-10-08 04:36" --device 1 2 --band 0.5 2 --band 1 10

    # 偽陽性率の見積もりに、地震と無関係な時間帯(1時間)を足す
    python template_match.py ... --null-hour "2026-10-05 02:00" --null-hour "2026-10-04 14:00"

--target は発生分（秒は不明なので分に切り捨てた時刻）。ラグ窓は発生分の+20〜+130秒。
"""
from __future__ import annotations

import argparse
import datetime as dt

import numpy as np
from scipy import signal

import detectlab as dl

FS = 100.0
JST = dt.timezone(dt.timedelta(hours=9))
LAG_FROM_S, LAG_TO_S = 20, 130
NULL_WIN_S = 110  # ラグ窓と同じ長さ
SCAN_BEFORE_S, SCAN_AFTER_S = 25 * 60, 35 * 60
NULL_EXCLUDE_S = (-60, 360)  # 他のtarget周りを偽陽性率の母集団から外す


def ncc(x: np.ndarray, t: np.ndarray) -> np.ndarray:
    """3軸合算の正規化相互相関。窓ごとの信号エネルギーで正規化する。"""
    m = len(t)
    num = sum(signal.fftconvolve(x[:, c], t[::-1, c], mode="valid") for c in range(3))
    cs = np.concatenate([[0.0], np.cumsum(np.sum(x ** 2, axis=1))])
    ex = cs[m:] - cs[:-m]
    return num / np.sqrt(np.maximum(ex, 1e-12) * np.sum(t ** 2))


def phase_randomize(t: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = np.empty_like(t)
    for c in range(3):
        f = np.fft.rfft(t[:, c])
        ph = rng.uniform(0, 2 * np.pi, len(f))
        ph[0] = 0
        out[:, c] = np.fft.irfft(np.abs(f) * np.exp(1j * ph), n=len(t))
    return out


def load(bucket: str, dev: int, start_s: float, end_s: float):
    data, st_us, _ = dl.load_s3_window(bucket, int(end_s * 1e6), end_s - start_s, dev)
    return data, st_us / 1e6


def z_in_window(cs: list[np.ndarray], mask: np.ndarray) -> tuple[float, int]:
    """cs[0]が本物、cs[1:]が偽テンプレート。ラグ窓内の最大値で比べる。"""
    real = cs[0][mask].max()
    sur = np.array([c[mask].max() for c in cs[1:]])
    return (real - sur.mean()) / sur.std(), int((sur >= real).sum())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--template-at", required=True, help="テンプレート切り出し開始(JST) 例 '2026-10-08 04:14:22'")
    p.add_argument("--template-len", type=float, default=80, help="テンプレート長[秒]（既定80）")
    p.add_argument("--target", action="append", required=True, help="対象の発生分(JST)。複数可")
    p.add_argument("--device", type=int, nargs="+", default=[1, 2])
    p.add_argument("--band", type=float, nargs=2, action="append", metavar=("LO", "HI"),
                   help="帯域[Hz]。複数可（既定 0.5-2 と 1-10）")
    p.add_argument("--nsur", type=int, default=30, help="偽テンプレート本数（既定30）")
    p.add_argument("--null-hour", action="append", default=[],
                   help="偽陽性率の見積もりに使う無関係な1時間の開始(JST)。複数可")
    p.add_argument("--bucket", help="rawバケット名（既定は NAMZ_RAW_BUCKET / terraform）")
    args = p.parse_args()

    bucket = dl.resolve_bucket(args.bucket)
    bands = [tuple(b) for b in args.band] if args.band else [(0.5, 2.0), (1.0, 10.0)]
    t0 = dl.at_to_us(args.template_at) / 1e6
    origins = [dl.at_to_us(s) / 1e6 for s in args.target]
    step = int(NULL_WIN_S * FS)

    for dev in args.device:
        td, tst = load(bucket, dev, t0 - 10, t0 + args.template_len + 10)
        for band in bands:
            rng = np.random.default_rng(1)
            tf = dl.bandpass(td, FS, *band)
            i0 = int(round((t0 - tst) * FS))
            tmpl = tf[i0:i0 + int(args.template_len * FS)]
            tmpls = [tmpl] + [phase_randomize(tmpl, rng) for _ in range(args.nsur)]

            def scan(start_s: float, end_s: float):
                xd, xst = load(bucket, dev, start_s, end_s)
                x = dl.bandpass(xd, FS, *band)
                cs = [ncc(x, t) for t in tmpls]
                return xst + np.arange(len(cs[0])) / FS, cs

            print(f"=== device{dev} band={band}")
            null_z: list[float] = []

            def collect_null(lag, cs, skip_events):
                for i in range(0, len(lag) - step, step):
                    if skip_events and any(
                            lag[i + step - 1] > e + NULL_EXCLUDE_S[0] and lag[i] < e + NULL_EXCLUDE_S[1]
                            for e in origins):
                        continue
                    m = np.zeros(len(lag), bool)
                    m[i:i + step] = True
                    null_z.append(z_in_window(cs, m)[0])

            for o_str, o in zip(args.target, origins):
                lag, cs = scan(o - SCAN_BEFORE_S, o + SCAN_AFTER_S)
                m = (lag >= o + LAG_FROM_S) & (lag <= o + LAG_TO_S)
                z, exceeded = z_in_window(cs, m)
                pk = cs[0][m].max()
                pk_lag = lag[m][cs[0][m].argmax()] - o
                print(f"  {o_str}  z={z:+5.1f}  偽超過={exceeded}/{args.nsur}  "
                      f"peak={pk:.3f}  lag={pk_lag:+.0f}s")
                collect_null(lag, cs, skip_events=True)

            for h in args.null_hour:
                hs = dl.at_to_us(h) / 1e6
                lag, cs = scan(hs, hs + 3600)
                collect_null(lag, cs, skip_events=False)

            if null_z:
                nz = np.array(null_z)
                print(f"  [null] n={len(nz)} 窓  z>2: {(nz > 2).mean():.3f}  "
                      f"z>2.8: {(nz > 2.8).mean():.3f}  z>3.5: {(nz > 3.5).mean():.3f}  "
                      f"max={nz.max():.1f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
