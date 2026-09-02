"""検出限界マップ（Artifact）に貼り込むSVGスニペットを`detection_events.csv`から生成する。

Claude Design Artifact「検出限界マップ」（M×震源距離の散布図＋観測点中心の方位図）の
座標計算はここに集約する。事例を追加したら`detection_range.py --out-md`同様、
このスクリプトも再実行してArtifactの中身を更新すること（Artifact自体の再publishは
このスクリプトではやらない・手作業でSVG片をHTMLに貼り込む）。

出力されるSVGはCSSクラス（`.gridline`/`.axis`/`.mark-good`等）に依存した見た目で、
単体では色が付かない。Artifact側で定義済みの同名クラス（ライト/ダーク両対応の
CSS変数を参照）と組み合わせて使う前提。

    # 散布図・方位図のSVG本体＋テーブル行＋回帰サマリを書き出す
    python detection_map_svg.py --out-dir ../docs/log/img
"""
from __future__ import annotations

import argparse
import math
import os

from detection_range import CSV_PATH, fit_good, load_events, r_pred
from detectlab import parse_station

PX_PER_KM = 0.279  # 方位図: 200km=55.8px の実測比を踏襲
SCATTER_X_MIN, SCATTER_X_MAX = 40.0, 900.0  # 震源距離[km]の表示レンジ（対数軸）
SCATTER_M_MIN, SCATTER_M_MAX = 3.0, 7.5     # マグニチュードの表示レンジ
SCATTER_AX_X0, SCATTER_AX_X1 = 70.0, 610.0  # 散布図 viewBox 0 0 640 360 内のプロット領域
SCATTER_AX_Y0, SCATTER_AX_Y1 = 330.0, 30.0
X_TICKS = [50, 100, 200, 300, 500, 700, 900]
M_TICKS = [3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0]
RING_KMS = [200, 400, 600, 800]           # 方位図: 距離の目盛(固定リング)
REACH_MAGNITUDES = [4, 5, 6, 7]           # 方位図: M別「目安到達円」


def sx(km: float) -> float:
    return SCATTER_AX_X0 + (SCATTER_AX_X1 - SCATTER_AX_X0) * (
        math.log10(km) - math.log10(SCATTER_X_MIN)
    ) / (math.log10(SCATTER_X_MAX) - math.log10(SCATTER_X_MIN))


def sy(magnitude: float) -> float:
    return SCATTER_AX_Y0 + (SCATTER_AX_Y1 - SCATTER_AX_Y0) * (magnitude - SCATTER_M_MIN) / (
        SCATTER_M_MAX - SCATTER_M_MIN
    )


def mark_svg(cx: float, cy: float, verdict: str) -> str:
    if verdict == "good":
        return f'<circle class="mark-good" cx="{cx:.1f}" cy="{cy:.1f}" r="7"/>'
    if verdict == "warning":
        return (f'<path class="mark-warning" d="M {cx:.1f} {cy-9:.1f} '
                 f'L {cx+7:.1f} {cy+3:.1f} L {cx-7:.1f} {cy+3:.1f} Z"/>')
    return (f'<path class="mark-critical" d="M {cx-6:.1f} {cy-6:.1f} L {cx+6:.1f} {cy+6:.1f} '
            f'M {cx+6:.1f} {cy-6:.1f} L {cx-6:.1f} {cy+6:.1f}" stroke-width="2.5" stroke="var(--critical)"/>')


def build_scatter_svg(events, a: float, b: float) -> str:
    lines = ['<svg viewBox="0 0 640 360" role="img" aria-label="マグニチュードと震源距離の散布図">']
    lines.append("  <g>")
    for t in X_TICKS:
        x = sx(t)
        lines.append(f'    <line class="gridline" x1="{x:.1f}" y1="30" x2="{x:.1f}" y2="330"/>')
    lines.append("  </g>")
    lines.append("  <g>")
    for t in M_TICKS:
        y = sy(t)
        lines.append(f'    <line class="gridline" x1="70" y1="{y:.1f}" x2="610" y2="{y:.1f}"/>')
    lines.append("  </g>")
    lines.append('  <line class="axis" x1="70" y1="330" x2="610" y2="330"/>')
    lines.append('  <line class="axis" x1="70" y1="30" x2="70" y2="330"/>')
    lines.append('  <g class="tick" text-anchor="middle">')
    for t in X_TICKS:
        lines.append(f'    <text x="{sx(t):.1f}" y="345">{t}</text>')
    lines.append("  </g>")
    lines.append('  <text class="axislabel" x="340" y="360" text-anchor="middle">震源距離 [km]（対数軸）</text>')
    lines.append('  <g class="tick" text-anchor="end">')
    for t in M_TICKS:
        lines.append(f'    <text x="63" y="{sy(t)+4:.1f}">{t}</text>')
    lines.append("  </g>")
    lines.append('  <text class="axislabel" x="20" y="180" text-anchor="middle" '
                 'transform="rotate(-90 20 180)">マグニチュード</text>')
    fx1, fy1 = sx(r_pred(a, b, SCATTER_M_MIN)), sy(SCATTER_M_MIN)
    fx2, fy2 = sx(r_pred(a, b, SCATTER_M_MAX)), sy(SCATTER_M_MAX)
    n_good = sum(1 for e in events if e.verdict == "good")
    lines.append(f'  <line class="fitline" x1="{fx1:.1f}" y1="{fy1:.1f}" x2="{fx2:.1f}" y2="{fy2:.1f}"/>')
    lines.append(f'  <text class="fitlabel" x="{fx2-140:.1f}" y="{fy2+40:.1f}">回帰の目安線(n={n_good}・good事例)</text>')
    lines.append('  <g class="mark-stroke">')
    for e in events:
        lines.append("    " + mark_svg(sx(e.hyp_km), sy(e.magnitude), e.verdict))
    lines.append("  </g>")
    lines.append('  <g class="numlabel" text-anchor="middle">')
    for e in events:
        lines.append(f'    <text x="{sx(e.hyp_km):.1f}" y="{sy(e.magnitude)-11:.1f}">{e.num}</text>')
    lines.append("  </g>")
    lines.append("</svg>")
    return "\n".join(lines)


def build_polar_svg(events, a: float, b: float) -> str:
    lines = ['<svg viewBox="0 0 600 460" role="img" aria-label="観測点を中心とした方位・距離マップ">']
    lines.append('  <g transform="translate(0,-20)">')
    for km in RING_KMS:
        lines.append(f'  <circle class="ring" cx="300" cy="300" r="{km*PX_PER_KM:.1f}"/>')
    lines.append('  <g class="ringlabel" text-anchor="start">')
    for km in RING_KMS:
        r = km * PX_PER_KM
        lines.append(f'    <text x="308" y="{300-r+8:.1f}">{km}km</text>')
    lines.append("  </g>")
    for m in REACH_MAGNITUDES:
        r = r_pred(a, b, m) * PX_PER_KM
        lines.append(f'  <circle class="ring" cx="300" cy="300" r="{r:.1f}" stroke="var(--fit-line)" opacity="0.7"/>')
    lines.append('  <g class="fitlabel" text-anchor="end">')
    for m in REACH_MAGNITUDES:
        r = r_pred(a, b, m) * PX_PER_KM
        lines.append(f'    <text x="292" y="{300-r+8:.1f}">M{m}</text>')
    lines.append("  </g>")
    lines.append('  <circle class="station" cx="300" cy="300" r="4.5"/>')
    lines.append('  <text class="stationlabel" x="300" y="320" text-anchor="middle">観測点(湯沢)</text>')
    lines.append('  <line class="axis" x1="300" y1="300" x2="300" y2="45"/>')
    lines.append('  <text class="tick" x="300" y="38" text-anchor="middle">N</text>')
    lines.append('  <g class="mark-stroke">')
    polar_events = [e for e in events if e.bearing is not None]
    for e in polar_events:
        r = e.hyp_km * PX_PER_KM
        brg = math.radians(e.bearing)
        x = 300 + r * math.sin(brg)
        y = 300 - r * math.cos(brg)
        lines.append("    " + mark_svg(x, y, e.verdict))
    lines.append("  </g>")
    lines.append('  <g class="numlabel">')
    for e in polar_events:
        r = e.hyp_km * PX_PER_KM
        brg = math.radians(e.bearing)
        x = 300 + r * math.sin(brg)
        y = 300 - r * math.cos(brg)
        lines.append(f'    <text x="{x:.1f}" y="{y-11:.1f}" text-anchor="middle">{e.num}</text>')
    lines.append("  </g>")
    lines.append("  </g>")
    lines.append("</svg>")
    excluded = [e for e in events if e.bearing is None]
    if excluded:
        names = "・".join(f"{e.name}(#{e.num})" for e in excluded)
        lines.append(f"<!-- 座標未記録のため方位図から除外: {names} -->")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", default=CSV_PATH, help="学習データCSV（既定: tools/detection_events.csv）")
    p.add_argument("--station", help='観測点座標 "lat,lon"（既定はdetectlab.pyと同じ湯沢町）')
    p.add_argument("--out-dir", required=True, help="scatter/polar SVGとテーブル行・サマリをこのディレクトリに書き出す")
    args = p.parse_args()

    station = parse_station(args.station)
    events = load_events(args.csv, station)
    a, b = fit_good(events)
    events = sorted(events, key=lambda e: e.hyp_km)
    for i, e in enumerate(events, 1):
        e.num = i

    os.makedirs(args.out_dir, exist_ok=True)

    scatter_path = os.path.join(args.out_dir, "detection-map-scatter.svg")
    with open(scatter_path, "w", encoding="utf-8") as f:
        f.write(build_scatter_svg(events, a, b) + "\n")

    polar_path = os.path.join(args.out_dir, "detection-map-polar.svg")
    with open(polar_path, "w", encoding="utf-8") as f:
        f.write(build_polar_svg(events, a, b) + "\n")

    table_path = os.path.join(args.out_dir, "detection-map-table.md")
    n_good = sum(1 for e in events if e.verdict == "good")
    n_warn = sum(1 for e in events if e.verdict == "warning")
    n_crit = sum(1 for e in events if e.verdict == "critical")
    with open(table_path, "w", encoding="utf-8") as f:
        f.write(f"<!-- fit: log10(震源距離)={a:.4f}+{b:.4f}*M  "
                f"n_good={n_good} n_warning={n_warn} n_critical={n_crit} n_total={len(events)} -->\n")
        f.write("<table>\n<thead><tr><th>#</th><th>地震</th><th>M</th><th class=\"num\">震源距離</th>"
                "<th>判定</th></tr></thead>\n<tbody>\n")
        for e in events:
            pred = r_pred(a, b, e.magnitude)
            ratio = e.hyp_km / pred
            f.write(f'<tr><td class="num">{e.num}</td><td>{e.name}</td><td class="num">{e.magnitude:.1f}</td>'
                    f'<td class="num">{e.hyp_km:.0f}km</td><td>{e.note}（比={ratio:.2f}）</td></tr>\n')
        f.write("</tbody>\n</table>\n")

    print(f"# fit: log10(震源距離) = {a:.4f} + {b:.4f}*M  "
          f"(good={n_good} warning={n_warn} critical={n_crit} total={len(events)})")
    print(f"# wrote {scatter_path}")
    print(f"# wrote {polar_path}")
    print(f"# wrote {table_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
