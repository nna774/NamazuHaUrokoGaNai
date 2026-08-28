from datetime import datetime, timedelta

import detection_range as dr
import scan_quakes as sq


def _entry(eid, at, anm, lat, lon, depth_m, mag, maxi="1"):
    sign = lambda v: f"+{v}" if v >= 0 else f"{v}"
    return {
        "eid": eid, "at": at, "anm": anm,
        "cod": f"{sign(lat)}{sign(lon)}{sign(depth_m)}/",
        "mag": str(mag), "maxi": maxi,
    }


def test_parse_cod_handles_sign_and_meters_to_km():
    assert sq.parse_cod("+40.6+142.3-50000/") == (40.6, 142.3, 50.0)
    assert sq.parse_cod("garbage") is None


def test_build_candidates_dedupes_by_eid_keeping_first():
    now = datetime.now(sq.JST)
    entries = [
        _entry("e1", (now - timedelta(hours=1)).isoformat(), "更新後", 37.0, 141.2, -60000, 4.0),
        _entry("e1", (now - timedelta(hours=2)).isoformat(), "更新前(古い報)", 37.0, 141.2, -60000, 3.8),
        _entry("e2", (now - timedelta(hours=1)).isoformat(), "M不明", 37.0, 141.2, -60000, None),
    ]
    entries[2].pop("mag")  # 震度速報相当（mag無し）を模す

    events = dr.load_events(dr.CSV_PATH, sq.DEFAULT_STATION)
    a, b = dr.fit_good(events)
    since = now - timedelta(days=1)

    out = sq.build_candidates(entries, sq.DEFAULT_STATION, a, b, since)
    assert len(out) == 1
    assert out[0].region == "更新後"  # 新しい報だけ残る、mag無しはスキップ


def test_build_candidates_stops_at_since_boundary():
    now = datetime.now(sq.JST)
    entries = [
        _entry("recent", now.isoformat(), "直近", 37.0, 141.2, -60000, 4.0),
        _entry("old", (now - timedelta(days=10)).isoformat(), "古い", 37.0, 141.2, -60000, 4.0),
    ]
    events = dr.load_events(dr.CSV_PATH, sq.DEFAULT_STATION)
    a, b = dr.fit_good(events)
    out = sq.build_candidates(entries, sq.DEFAULT_STATION, a, b, since=now - timedelta(days=3))
    assert [c.region for c in out] == ["直近"]
