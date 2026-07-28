"""tenki.jp の地震詳細URLから諸元を取り、detectlab で解析図を出すラッパ。

tenki.jp のページから 発生時刻・緯度経度・深さ・M・震源地 を抽出し、detectlab.py に
--at と --eew を渡して P/S到達窓つきの解析図を1コマンドで生成する。震源距離から
既定バンドも自動選択する（遠いほど低周波寄り）。

    python tenki_view.py <tenki地震詳細URL> --minutes 8 --out fig.png

注意:
- tenki の発生時刻は「HH時MM分頃」の分単位（秒なし）。到達窓に±30秒程度の不定性が乗る。
- 確定前(速報段階)のページは緯度経度が「---」で取れないことがある。その時は確定を待つか、
  detectlab.py に手で --eew を渡せ。
- detectlab と同じく、波形はS3(raw/)から取る。バケット/AWS認証はそのまま渡る。
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detectlab  # noqa: E402  （震源ジオメトリ・観測点解決を再利用）
from detectlab import JST  # noqa: E402

_DETECTLAB = Path(__file__).resolve().parent / "detectlab.py"


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (detectlab tenki_view)"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310  （tenki固定用途）
        return r.read().decode("utf-8", "replace")


def parse_tenki(html: str) -> dict:
    """tenki.jp 地震詳細HTMLから諸元を抽出する。取れない項目は None。

    テーブルは <th>ラベル</th><td>値</td>。発生時刻は id で一意に取れる。
    """

    def find(pat: str) -> str | None:
        m = re.search(pat, html, re.S)
        return m.group(1).strip() if m else None

    def find_td(label: str) -> str | None:
        """<th>ラベル</th><td>…</td> の td 中身を、内側のタグ(リンク等)を剥がして返す。"""
        m = re.search(label + r"</th>\s*<td[^>]*>(.*?)</td>", html, re.S)
        if not m:
            return None
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() or None

    out: dict = {"origin_us": None, "lat": None, "lon": None, "depth_km": None,
                 "mag": None, "region": None, "max_intensity": None}

    dt_raw = find(r'id="earthquake-generating-datetime">([^<]+)<')
    if dt_raw:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})時(\d{1,2})分", dt_raw)
        if m:
            y, mo, d, hh, mi = (int(x) for x in m.groups())
            dt = datetime(y, mo, d, hh, mi, 0, tzinfo=JST)
            out["origin_us"] = int(dt.timestamp() * 1e6)

    m = re.search(r"(北緯|南緯)\s*([\d.]+)\s*度", html)
    if m:
        out["lat"] = float(m.group(2)) * (1 if m.group(1) == "北緯" else -1)
    m = re.search(r"(東経|西経)\s*([\d.]+)\s*度", html)
    if m:
        out["lon"] = float(m.group(2)) * (1 if m.group(1) == "東経" else -1)

    depth = find_td("深さ")
    if depth:
        m = re.search(r"([\d.]+)\s*km", depth)
        if m:
            out["depth_km"] = float(m.group(1))
        elif "ごく浅い" in depth:
            out["depth_km"] = 10.0  # 気象庁「ごく浅い」の慣例値

    mag = find_td("マグニチュード")
    if mag:
        m = re.search(r"([\d.]+)", mag)
        out["mag"] = float(m.group(1)) if m else None

    out["region"] = find_td("震源地")
    out["max_intensity"] = find_td("最大震度")
    return out


def default_band(hypo_km: float) -> tuple[str, str]:
    """震源距離から既定バンド[Hz]を選ぶ。遠いほど低周波寄り＝ノイズ帯と重なる。"""
    if hypo_km > 700:
        return ("0.3", "1.5")
    if hypo_km > 300:
        return ("0.5", "3")
    return ("1", "10")


def main() -> int:
    p = argparse.ArgumentParser(
        description="tenki.jp のURLから detectlab の解析図を出す",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="その他のオプション(--band/--thr/--out/--bucket 等)はそのまま detectlab.py に渡る。",
    )
    p.add_argument("url", help="tenki.jp の地震詳細URL")
    p.add_argument("--minutes", type=float, default=8.0, help="窓長[分]（既定8）")
    p.add_argument("--station", help='観測点座標 "lat,lon"（距離推定と detectlab 用）')
    p.add_argument("--dry-run", action="store_true", help="detectlab を実行せずコマンドだけ表示")
    args, passthrough = p.parse_known_args()

    q = parse_tenki(fetch_html(args.url))
    if q["origin_us"] is None or q["lat"] is None or q["lon"] is None:
        raise SystemExit(
            "緯度経度または発生時刻を取得できなかった（速報段階で「---」の可能性）。\n"
            "確定ページを待つか、detectlab.py に手で --at/--eew を渡せ。"
        )
    depth = q["depth_km"] if q["depth_km"] is not None else 10.0
    origin_str = datetime.fromtimestamp(q["origin_us"] / 1e6, JST).strftime("%Y-%m-%d %H:%M:%S")

    st_lat, st_lon = detectlab.parse_station(args.station)
    hypo, epi = detectlab.hypocentral_km(q["lat"], q["lon"], depth, st_lat, st_lon)
    mag = f"M{q['mag']:g}" if q["mag"] is not None else "M不明"
    depth_note = "" if q["depth_km"] is not None else "(不明→10km仮定)"
    print(f"# {q['region']}  {mag}  深さ{depth:g}km{depth_note}  発生 {origin_str} (分単位)")
    print(f"# 最大{q['max_intensity']}  震央距離{epi:.0f}km 震源距離{hypo:.0f}km")

    eew = f"{q['lat']},{q['lon']},{depth:g},{origin_str}"
    argv = [sys.executable, str(_DETECTLAB), "--at", origin_str, "--eew", eew,
            "--minutes", f"{args.minutes:g}"]
    if args.station:
        argv += ["--station", args.station]
    if "--band" not in passthrough:
        argv += ["--band", *default_band(hypo)]
    argv += passthrough

    if args.dry_run:
        print("+ " + shlex.join(argv))
        return 0
    print("+ detectlab " + shlex.join(argv[2:]))
    return subprocess.run(argv).returncode


if __name__ == "__main__":
    sys.exit(main())
