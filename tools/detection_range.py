"""事後解析事例から「投げる価値があるか」の目安距離を回帰し、表を出す。

data源は `detection_events.csv`（verdict: good/warning/critical）。verdictが
good（確定検知・probable）の事例だけで log10(震源距離) = a + b*M を最小二乗フィットし、
その予測値の0.8〜1.6倍を「投げる価値ありレンジ」とする（過去の成功事例の実測/予測比が
概ねこの帯に収まることから。外れ値の扱いは docs/detection_range.md 参照）。

    # 表を再生成してdocs用Markdownに書き出す
    python detection_range.py --out-md ../docs/detection_range.md

    # 手元の候補地震が「投げる価値があるか」その場で判定
    python detection_range.py --check 4.2 250
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from dataclasses import dataclass

import numpy as np

from detectlab import DEFAULT_STATION, hypocentral_km, parse_station

BAND_LO, BAND_HI = 0.8, 1.6  # 「投げる価値ありレンジ」の予測値に対する倍率
CSV_PATH = os.path.join(os.path.dirname(__file__), "detection_events.csv")


@dataclass
class Event:
    id: str
    name: str
    date: str
    magnitude: float
    hyp_km: float
    epi_km: float
    verdict: str
    note: str
    log: str


def load_events(csv_path: str, station: tuple[float, float]) -> list[Event]:
    st_lat, st_lon = station
    events = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            depth = float(row["depth_km"])
            if row["lat"] and row["lon"]:
                hyp, epi = hypocentral_km(float(row["lat"]), float(row["lon"]), depth, st_lat, st_lon)
            else:
                epi = float(row["epi_km_override"])
                hyp = math.hypot(epi, depth)
            events.append(Event(
                id=row["id"], name=row["name"], date=row["date"], magnitude=float(row["magnitude"]),
                hyp_km=hyp, epi_km=epi, verdict=row["verdict"], note=row["note"], log=row["log"],
            ))
    return events


def fit_good(events: list[Event]) -> tuple[float, float]:
    """log10(hyp_km) = a + b*M を verdict=='good' の事例だけで最小二乗フィット。"""
    good = [e for e in events if e.verdict == "good"]
    M = np.array([e.magnitude for e in good])
    logR = np.array([math.log10(e.hyp_km) for e in good])
    A = np.vstack([np.ones_like(M), M]).T
    (a, b), *_ = np.linalg.lstsq(A, logR, rcond=None)
    return float(a), float(b)


def r_pred(a: float, b: float, magnitude: float) -> float:
    return 10 ** (a + b * magnitude)


def worth_asking_band(a: float, b: float, magnitude: float) -> tuple[float, float]:
    rp = r_pred(a, b, magnitude)
    return BAND_LO * rp, BAND_HI * rp


def zone_of(a: float, b: float, magnitude: float, hyp_km: float) -> str:
    lo, hi = worth_asking_band(a, b, magnitude)
    if hyp_km < lo:
        return "近すぎ(ほぼ確実に捕れる・優先度低)"
    if hyp_km > hi:
        return "遠すぎ(恐らく埋没・埋没側の実例集めが目的の時だけ)"
    return "投げる価値あり(境界帯)"


def print_report(events: list[Event], a: float, b: float) -> None:
    print(f"# fit: log10(震源距離) = {a:.4f} + {b:.4f}*M  (verdict=good の{sum(1 for e in events if e.verdict=='good')}件)")
    print()
    print("## 事例と回帰の当てはまり")
    for e in sorted(events, key=lambda e: e.hyp_km):
        pred = r_pred(a, b, e.magnitude)
        ratio = e.hyp_km / pred
        print(f"  {e.id:24s} M{e.magnitude:.1f}  実測={e.hyp_km:6.0f}km  予測={pred:6.0f}km  "
              f"比={ratio:.2f}  [{e.verdict}]")
    print()
    print(f"## 投げる価値ありレンジ（予測の{BAND_LO}〜{BAND_HI}倍）")
    for m10 in range(30, 76, 5):
        mv = m10 / 10
        rp = r_pred(a, b, mv)
        lo, hi = worth_asking_band(a, b, mv)
        print(f"  M{mv:.1f}: 目安={rp:6.0f}km  レンジ=[{lo:6.0f}, {hi:6.0f}]km")


def write_markdown(path: str, events: list[Event], a: float, b: float) -> None:
    lines = []
    lines.append("# 検出限界の目安表（自動生成）")
    lines.append("")
    lines.append(f"`tools/detection_range.py`で`tools/detection_events.csv`（{len(events)}件、"
                  f"うちgood={sum(1 for e in events if e.verdict=='good')}件）から生成。"
                  "**このファイルは手で編集せず、事例を追加したらスクリプトを再実行して上書きすること。**")
    lines.append("")
    lines.append(f"回帰式（verdict=good のみでフィット）: `log10(震源距離[km]) = {a:.4f} + {b:.4f} * M`")
    lines.append("")
    lines.append(f"「投げる価値ありレンジ」は回帰予測の{BAND_LO}〜{BAND_HI}倍。過去の成功事例の実測/予測比が"
                  "概ねこの帯に収まることから決めた目安で、統計的に導出した確率ではない。")
    lines.append("")
    lines.append("## 使い方")
    lines.append("")
    lines.append("高度利用者向けEEWが出た地震のうち、上の表で自分のいる震源距離が「投げる価値ありレンジ」に"
                  "入っていたら[docs/post_hoc_detection.md](post_hoc_detection.md)の手順で確認する。"
                  "レンジより近い（＝ほぼ確実に捕れている）ものは優先度低、レンジより遠い（＝恐らく埋没）ものは"
                  "埋没側の実例を増やしたい時だけ拾えばよい。震源距離が分からない時は"
                  "`python tools/detection_range.py --check <M> <震源距離km>`で判定できる。"
                  "人間が気づいたものだけに頼らず機械的に洗い出すなら"
                  "`python tools/scan_quakes.py`（気象庁の公開地震一覧から該当するものを抽出し、"
                  "`--eew`込みの`detectlab.py`呼び出しまで出す）。")
    lines.append("")
    lines.append("## なぜ「投げる価値ありレンジ」なのか（帯であってシャープな円ではない理由）")
    lines.append("")
    lines.append("物理的には距離減衰で「震度 ∝ M − k・log₁₀(距離)」という形になるので、"
                  "マグニチュードが大きいほど遠くまで捕れるという傾向自体は妥当。ただしこの回帰は"
                  f"n={sum(1 for e in events if e.verdict=='good')}・対数空間の当てはまりも緩く、"
                  "同じM4.0で震源距離220kmが「微妙」・273kmが「probable」という逆転が実際に起きている"
                  "（方位・放射パターン、個々の地震の高周波の出方の違い、判定した瞬間の背景ノイズの"
                  "当たり外れが、M・距離だけでは説明できない分散を生んでいる）。**目安であって"
                  "保証される検出円ではない。** 事例が増えるほど回帰は締まっていくはずなので、"
                  "特に境界帯・埋没側の実例を優先して集める価値がある。")
    lines.append("")
    lines.append("## マグニチュード別 投げる価値ありレンジ")
    lines.append("")
    lines.append("| M | 目安距離(震源距離) | 投げる価値ありレンジ |")
    lines.append("|---|---|---|")
    for m10 in range(30, 76, 5):
        mv = m10 / 10
        rp = r_pred(a, b, mv)
        lo, hi = worth_asking_band(a, b, mv)
        lines.append(f"| {mv:.1f} | {rp:.0f}km | {lo:.0f}〜{hi:.0f}km |")
    lines.append("")
    lines.append("## 学習データ（事例が増えたらここに追記→再生成）")
    lines.append("")
    lines.append("| id | 地震 | 日付 | M | 震源距離 | 判定 | 予測比 |")
    lines.append("|---|---|---|---|---|---|---|")
    for e in sorted(events, key=lambda e: e.hyp_km):
        pred = r_pred(a, b, e.magnitude)
        ratio = e.hyp_km / pred
        lines.append(f"| `{e.id}` | {e.name} | {e.date} | {e.magnitude:.1f} | {e.hyp_km:.0f}km | {e.verdict} | {ratio:.2f} |")
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"# wrote {path}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", default=CSV_PATH, help="学習データCSV（既定: tools/detection_events.csv）")
    p.add_argument("--station", help='観測点座標 "lat,lon"（既定はdetectlab.pyと同じ湯沢町）')
    p.add_argument("--check", nargs=2, metavar=("M", "HYP_KM"), type=float,
                   help="候補地震(マグニチュード, 震源距離km)が投げる価値があるか判定して終了")
    p.add_argument("--out-md", help="docs用Markdownをこのパスに書き出す")
    args = p.parse_args()

    station = parse_station(args.station)
    events = load_events(args.csv, station)
    a, b = fit_good(events)

    if args.check:
        mv, hyp = args.check
        zone = zone_of(a, b, mv, hyp)
        lo, hi = worth_asking_band(a, b, mv)
        print(f"M{mv} 震源距離{hyp:.0f}km  → {zone}  (投げる価値ありレンジ: {lo:.0f}〜{hi:.0f}km)")
        return 0

    print_report(events, a, b)
    if args.out_md:
        write_markdown(args.out_md, events, a, b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
