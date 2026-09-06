"""気象庁の地震情報一覧から「投げる価値があるか」を機械的に絞り込む。

`detection_range.py`のverdict回帰と同じ考え方を使い、直近の地震のうち観測点からの
震源距離が「投げる価値ありレンジ」（回帰予測の0.8〜1.6倍）に入るものだけを一覧にする。
遠すぎ（恐らく埋没）側もデフォルトで一緒に出す——埋没側の実例が手薄なため
（[docs/detection_range.md](../docs/detection_range.md)参照）、意図的に拾う価値がある。

データ源は気象庁の公開JSON(`https://www.jma.go.jp/bosai/quake/data/list.json`、
認証不要・ローリングで直近約1ヶ月ぶん)。同一地震の複数報(`eid`が同じ)は最新のものだけ残す。

    # 直近3日、投げる価値ありレンジ+遠すぎ(埋没候補)を一覧
    python scan_quakes.py

    # 直近7日、近すぎ(ほぼ確実に捕れる)も含めて全部見る
    python scan_quakes.py --days 7 --all

    # オフラインのJSONで試す（list.jsonのダンプを渡す）
    python scan_quakes.py --json-path saved_list.json
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from detectlab import DEFAULT_STATION, hypocentral_km, parse_station
from detection_range import CSV_PATH, fit_good, load_events, r_pred, worth_asking_band, zone_of

JMA_LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
JST = timezone(timedelta(hours=9))
_COD_RE = re.compile(r"^([+-][\d.]+)([+-][\d.]+)([+-][\d.]+)/$")

# 一覧に出すゾーン（既定）。近すぎ(ほぼ確実に捕れる)は情報量が薄いので既定では隠す。
DEFAULT_ZONE_KEYWORDS = ("投げる価値あり", "遠すぎ")


@dataclass
class Candidate:
    eid: str
    at: str  # JST ISO8601文字列（気象庁発表・分単位）
    region: str
    magnitude: float
    lat: float
    lon: float
    depth_km: float
    max_intensity: str
    hyp_km: float
    zone: str


def fetch_list(url: str = JMA_LIST_URL) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NamazuHaUrokoGaNai scan_quakes)"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310  （気象庁公開JSON固定用途）
        return json.loads(r.read().decode("utf-8"))


def parse_cod(cod: str) -> tuple[float, float, float] | None:
    """"+40.6+142.3-50000/" -> (lat, lon, depth_km)。深さ不明("ND"等)はNone。"""
    m = _COD_RE.match(cod)
    if not m:
        return None
    lat, lon, depth_m = (float(x) for x in m.groups())
    return lat, lon, abs(depth_m) / 1000.0


def build_candidates(
    entries: list[dict], station: tuple[float, float], a: float, b: float,
    since: datetime,
) -> list[Candidate]:
    st_lat, st_lon = station
    seen_eids: set[str] = set()
    out: list[Candidate] = []
    for e in entries:
        eid = e.get("eid")
        if not eid or eid in seen_eids:
            continue  # 同一地震の古い報は捨てる（listは新しい順）
        at_str = e.get("at")
        if not at_str:
            continue
        at = datetime.fromisoformat(at_str)
        if at < since:
            break  # listは新しい順なので、窓の外に出たら以降も全部窓の外
        mag_raw = e.get("mag")
        cod_raw = e.get("cod")
        if not mag_raw or not cod_raw:
            continue
        try:
            mag = float(mag_raw)
        except ValueError:
            continue
        parsed = parse_cod(cod_raw)
        if parsed is None:
            continue
        lat, lon, depth_km = parsed
        seen_eids.add(eid)

        hyp_km, _epi_km = hypocentral_km(lat, lon, depth_km, st_lat, st_lon)
        zone = zone_of(a, b, mag, hyp_km)
        out.append(Candidate(
            eid=eid, at=at_str, region=e.get("anm", "?"), magnitude=mag,
            lat=lat, lon=lon, depth_km=depth_km, max_intensity=e.get("maxi", "-"),
            hyp_km=hyp_km, zone=zone,
        ))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=float, default=3.0, help="何日前まで遡るか（既定3日）")
    p.add_argument("--station", help='観測点座標 "lat,lon"（既定はdetectlab.pyと同じ湯沢町）')
    p.add_argument("--csv", default=CSV_PATH, help="回帰用学習データCSV（既定: detection_events.csv）")
    p.add_argument("--all", action="store_true", help="「近すぎ」ゾーンも含めて全部表示する")
    p.add_argument("--json-path", help="list.jsonを直接指定（オフラインテスト用。省略時は気象庁から取得）")
    args = p.parse_args()

    station = parse_station(args.station)
    a, b = fit_good(load_events(args.csv, station))
    since = datetime.now(JST) - timedelta(days=args.days)

    if args.json_path:
        with open(args.json_path, encoding="utf-8") as f:
            entries = json.load(f)
    else:
        entries = fetch_list()

    candidates = build_candidates(entries, station, a, b, since)
    if not args.all:
        candidates = [c for c in candidates if any(k in c.zone for k in DEFAULT_ZONE_KEYWORDS)]

    print(f"# 気象庁地震一覧より直近{args.days:g}日・{len(candidates)}件"
          f"（回帰: log10(震源距離)={a:.4f}+{b:.4f}*M）")
    if not candidates:
        print("(該当なし)")
        return 0

    for c in sorted(candidates, key=lambda c: c.at, reverse=True):
        lo, hi = worth_asking_band(a, b, c.magnitude)
        at_str = c.at[:16].replace("T", " ")
        eew = f"{c.lat},{c.lon},{c.depth_km:g},{at_str}"
        print(f"\n[{c.at}] {c.region}  M{c.magnitude:g}  震源距離{c.hyp_km:.0f}km"
              f"（レンジ{lo:.0f}〜{hi:.0f}km）  最大震度{c.max_intensity}  → {c.zone}")
        print(f'  detectlab.py --at "{at_str}" --eew "{eew}" --minutes 10 --device 1 2')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
