"""既知の震央から、センサの水平軸の方位(+軸が真北から時計回り何度を向くか)を推定する（試作）。

原理: 地殻内を下から来るP波の質点運動は伝播方向に直線偏光する。つまり水平面では
**震央←→観測点を結ぶ線上**で動き、同じ時間関数で上下にも動く。
- 水平2軸のP初動窓の主成分(PCA)で、水平の動きの軸が機体座標のどの向きか分かる
- 主成分方向と上下成分の相関の符号で、その向きが「震央から遠ざかる側」かどうかが決まる
  （圧縮でも膨張でも質点運動は(遠ざかる水平, 上)か(近づく水平, 下)の組なので、符号が頑健）
- 観測点→震央の方位 b が既知なので、「遠ざかる側」の真方位は b+180°。これと機体座標の角度から
  +H1軸の真方位α1が出る

**結果: この方法では方位を出せなかった**（docs/log/2026-10-29-azimuth-from-epicenter-trial.md）。
震央方位bが78〜174°に散らばる9イベントで、機体座標でのP初動の水平偏光軸φが70〜100°(ほぼy軸)に
固定され、震央方位に追従しなかった。機体・土台の共振方向を拾っているとみられる。試作の記録として残す。

    python estimate_azimuth.py --device 1 2 \\
      --ev "chiba-m5.4,2026-10-29 00:08:32,35.7,140.7,50" \\
      --ev "ibaraki-m4.9,2026-09-29 04:45:46,36.1,139.9,50"

`--ev` の時刻は、そのイベントのP到達の近く(±数十秒)でよい（detectのonset_us等）。
その近傍のSTA/LTA最初の閾値超過をP初動とみなす。窓は初動の-0.5秒〜+`--win`秒。

前提と限界:
- 機体座標(x,y,z)が**右手系**で、重力軸が上向きに+1g(加速度センサの出力)を読むと仮定している。
  重力軸の符号が負なら左手系として扱う(出力の「重力軸の符号」を見ろ)。実機で一度叩いて確かめるのが確実。
- 水平2軸は重力軸以外の2軸を(h1,h2)=((g+1)%3,(g+2)%3)として右手系の順に並べる。
- 震央方位は緯度経度の平面近似で、観測点座標は町レベル(`station.py`の既定)。数度の誤差は残る。
- 1回の地震では堅牢でない。直線性・上下相関が弱いイベントは除き、複数イベントの円平均で見ること。
"""
from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone, timedelta

import numpy as np

import detectlab as dl
from station import bearing_deg, parse_station

JST = timezone(timedelta(hours=9))
BAND = (1.0, 10.0)
AXES = "xyz"


def estimate(data: np.ndarray, fs: float, start_us: int, t_us: int, bearing_to_eq: float,
             win_s: float, band_range: tuple[float, float] = BAND, thr: float = 4.0, lta_s: float = 30.0, search_before: float = 45.0,
             search_after: float = 15.0) -> dict | None:
    # 初動の検出は常に標準帯域(1-10Hz)で行う。低帯域だと別の過渡(ノイズ)で誤トリガーする。
    _b, ratio, onsets, _rect, _vec = dl.analyze(data, fs, start_us, BAND, "xyz",
                                                0.5, lta_s, thr, 2.0)
    band = dl.bandpass(data, fs, *band_range)  # 偏光の計算に使う帯域
    cand = [o for o in onsets if t_us - search_before * 1e6 <= o <= t_us + search_after * 1e6]
    if not cand:
        return None
    onset_us = cand[0]
    pre = data[: max(1, int(30 * fs))]
    g = int(np.argmax(np.abs(pre.mean(axis=0))))
    s = 1.0 if pre.mean(axis=0)[g] > 0 else -1.0
    h1, h2 = (g + 1) % 3, (g + 2) % 3
    i0 = int(round((onset_us - start_us) / 1e6 * fs - 0.5 * fs))
    i1 = int(round((onset_us - start_us) / 1e6 * fs + win_s * fs))
    seg = band[max(0, i0):i1]
    hh = seg[:, [h1, h2]]
    up = s * seg[:, g]
    cov = hh.T @ hh
    w, v = np.linalg.eigh(cov)
    u = v[:, 1]  # 主成分(最大固有値)
    lin = float(w[1] / max(w.sum(), 1e-12))
    proj = hh @ u
    r = float(np.sum(up * proj) / math.sqrt(max(np.sum(up ** 2) * np.sum(proj ** 2), 1e-12)))
    if r < 0:
        u = -u  # +uが「震央から遠ざかる側」になるようにそろえる
    phi = math.degrees(math.atan2(u[1], u[0]))
    away = (bearing_to_eq + 180.0) % 360
    alpha1 = (away + phi) % 360 if s > 0 else (away - phi) % 360
    return {
        "onset_us": onset_us, "g": g, "gs": s, "h1": h1, "h2": h2, "lin": lin, "r": abs(r),
        "phi": phi, "alpha1": alpha1, "ratio": float(ratio[max(0, i0):i1].max()),
        "amp": float(np.sqrt(np.mean(hh ** 2))),
    }


def circ_mean_std(deg: list[float]) -> tuple[float, float]:
    a = np.radians(deg)
    c, s = np.cos(a).mean(), np.sin(a).mean()
    R = math.hypot(c, s)
    return math.degrees(math.atan2(s, c)) % 360, math.degrees(math.sqrt(-2 * math.log(max(R, 1e-12))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--ev", action="append", required=True,
                    metavar='"名前,YYYY-MM-DD HH:MM:SS,lat,lon,depth"',
                    help="--from-event時は '名前,<event_idの数字部 例59580602>,lat,lon,depth'")
    ap.add_argument("--from-event", action="store_true",
                    help="rawでなく保存済みevents/の波形を読む（rawは60日で消えるので古い地震はこちら）。"
                         "時刻はmeta.jsonのonset基準。LTAは10秒に縮める")
    ap.add_argument("--search-before", type=float, default=45.0, help="基準時刻より前に初動を探す秒数")
    ap.add_argument("--search-after", type=float, default=15.0,
                    help="基準時刻より後ろに探す秒数（手動昇格は基準が発生時刻なので120程度に伸ばす）")
    ap.add_argument("--device", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--win", type=float, default=2.0, help="初動からの窓の長さ[秒]（既定2.0）")
    ap.add_argument("--band", type=float, nargs=2, default=list(BAND), metavar=("LO", "HI"),
                    help="帯域[Hz]（既定1 10）。機体の共振(約4Hz)を避けたい時は 0.5 2.5 など")
    ap.add_argument("--min-lin", type=float, default=0.8, help="集計に使う直線性の下限")
    ap.add_argument("--min-r", type=float, default=0.6, help="集計に使う上下相関|r|の下限")
    ap.add_argument("--station")
    ap.add_argument("--bucket")
    args = ap.parse_args()
    st_lat, st_lon = parse_station(args.station)
    bucket = dl.resolve_bucket(args.bucket)

    good: dict[int, list[float]] = {d: [] for d in args.device}
    print(f"# 観測点 {st_lat},{st_lon}  窓=初動-0.5s〜+{args.win:g}s  帯域{args.band[0]:g}-{args.band[1]:g}Hz")
    print("# α1 = +H1軸(重力軸の次の軸)の真方位[度, 時計回り]。使うのは 直線性>=%.2f かつ |r|>=%.2f" %
          (args.min_lin, args.min_r))
    for ev in args.ev:
        name, ts, lat, lon, _dep = ev.split(",")
        t_us = None if args.from_event else dl.at_to_us(ts)
        b = bearing_deg(float(lat), float(lon), st_lat, st_lon)
        print(f"\n[{name}] {ts}  震央方位(観測点→震央)={b:.0f}°")
        for dev in args.device:
            if args.from_event:
                eid = f"{dev:04d}-{ts}"
                try:
                    t_us = dl.load_event_onset_us(bucket, eid)
                    data, start_us, fs = dl.load_s3_event(bucket, eid, near_us=t_us)
                except Exception as exc:  # noqa: BLE001
                    print(f"  device{dev}: event {eid} を読めない ({type(exc).__name__})")
                    continue
            else:
                data, start_us, fs = dl.load_s3_window(bucket, int(t_us + 60e6), 180.0, dev)
            if data.shape[0] == 0:
                print(f"  device{dev}: 波形なし")
                continue
            e = estimate(data, fs, start_us, t_us, b, args.win, tuple(args.band),
                         lta_s=10.0 if args.from_event else 30.0,
                         search_before=args.search_before, search_after=args.search_after)
            if e is None:
                print(f"  device{dev}: 初動なし(STA/LTA閾値未達)")
                continue
            ok = e["lin"] >= args.min_lin and e["r"] >= args.min_r
            on = datetime.fromtimestamp(e["onset_us"] / 1e6, JST)
            print(f"  device{dev}: 初動{on:%H:%M:%S.%f}"[:-3] +
                  f"  重力軸={AXES[e['g']]}({'+' if e['gs'] > 0 else '-'})  H1={AXES[e['h1']]} H2={AXES[e['h2']]}"
                  f"  直線性={e['lin']:.2f} |r|={e['r']:.2f}  STA/LTA={e['ratio']:.1f}"
                  f"  α1={e['alpha1']:.0f}°  {'採用' if ok else '除外'}")
            if ok:
                good[dev].append(e["alpha1"])
    print("\n# 採用イベントの円平均(±は円標準偏差)")
    for dev, vals in good.items():
        if vals:
            m, sd = circ_mean_std(vals)
            print(f"  device{dev}: n={len(vals)}  α1={m:.0f}° ±{sd:.0f}°   個別={[round(x) for x in vals]}")
        else:
            print(f"  device{dev}: 採用イベントなし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
