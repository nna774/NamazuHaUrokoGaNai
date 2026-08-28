import detection_range as dr


def test_load_events_computes_hyp_km_from_latlon_or_override():
    events = dr.load_events(dr.CSV_PATH, dr.DEFAULT_STATION)
    by_id = {e.id: e for e in events}

    # 座標ありの事例は震央距離<震源距離(深さ分だけ伸びる)
    urakawa = by_id["urakawa-oki-m6.0"]
    assert urakawa.epi_km < urakawa.hyp_km

    # 座標未記録・epi_km_override指定の事例も読める
    old_fukushima = by_id["fukushima-oki-m4.0-1"]
    assert old_fukushima.epi_km == 268.0


def test_ids_are_unique():
    events = dr.load_events(dr.CSV_PATH, dr.DEFAULT_STATION)
    ids = [e.id for e in events]
    assert len(ids) == len(set(ids))


def test_fit_uses_only_good_verdict():
    events = dr.load_events(dr.CSV_PATH, dr.DEFAULT_STATION)
    a, b = dr.fit_good(events)
    good_n = sum(1 for e in events if e.verdict == "good")
    assert good_n >= 5  # 回帰が数件だけの偶然に左右されない最低限の件数
    # 傾きは正(マグニチュードが大きいほど遠くまで届く)
    assert b > 0


def test_zone_of_orders_near_core_far():
    events = dr.load_events(dr.CSV_PATH, dr.DEFAULT_STATION)
    a, b = dr.fit_good(events)
    rp = dr.r_pred(a, b, 4.5)

    assert "近すぎ" in dr.zone_of(a, b, 4.5, rp * 0.3)
    assert "投げる価値あり" in dr.zone_of(a, b, 4.5, rp * 1.0)
    assert "遠すぎ" in dr.zone_of(a, b, 4.5, rp * 3.0)
