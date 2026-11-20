"""events.list_page のフィルタ挙動（人工地震フラグの隠し込み）。

DynamoDBに触らず、全件scanだけ差し替えてフィルタ/ソートの純粋ロジックを確認する。
"""

import pytest

from common import events


def _stub_scan(monkeypatch, items):
    monkeypatch.setattr(events, "_scan_all", lambda: items)


def _ids(items):
    return [it["event_id"] for it in items]


def _items():
    # list_page は scan 結果を in-place ソートするので毎回新しい list を返す
    return [
        # 確定済み
        {"event_id": "0001-10", "onset_us": 10, "cloud_confirmed": True},
        # 評価済みだが未確定（非該当）
        {"event_id": "0001-20", "onset_us": 20, "checked": True},
        # 未評価（速報のみ・評価待ち）
        {"event_id": "0001-30", "onset_us": 30},
        # 確定済みだが人工地震フラグ
        {"event_id": "0001-40", "onset_us": 40, "cloud_confirmed": True, "artificial": True},
    ]


def test_default_hides_checked_and_artificial(monkeypatch):
    _stub_scan(monkeypatch, _items())
    items, total = events.list_page(show_all=False)
    # 非該当(0001-20)と人工地震(0001-40)は隠れ、新しい順に並ぶ
    assert _ids(items) == ["0001-30", "0001-10"]
    assert total == 2


def test_show_all_includes_everything(monkeypatch):
    _stub_scan(monkeypatch, _items())
    items, total = events.list_page(show_all=True)
    assert _ids(items) == ["0001-40", "0001-30", "0001-20", "0001-10"]
    assert total == 4


def test_artificial_hidden_even_when_confirmed(monkeypatch):
    # 確定済みでも artificial が立っていれば既定では出さない
    _stub_scan(monkeypatch, [it for it in _items() if it["event_id"] == "0001-40"])
    items, total = events.list_page(show_all=False)
    assert items == [] and total == 0


def test_manual_shown_by_default(monkeypatch):
    # 手動イベントは checked かつ未確定だが、manual フラグで既定一覧に出る
    _stub_scan(monkeypatch, [{"event_id": "0001-50", "onset_us": 50,
                              "checked": True, "manual": True}])
    items, total = events.list_page(show_all=False)
    assert _ids(items) == ["0001-50"] and total == 1


def test_manual_but_artificial_hidden(monkeypatch):
    # 手動でも artificial が立っていれば既定では隠す
    _stub_scan(monkeypatch, [{"event_id": "0001-60", "onset_us": 60,
                              "checked": True, "manual": True, "artificial": True}])
    items, total = events.list_page(show_all=False)
    assert items == [] and total == 0


def test_device_filter(monkeypatch):
    # device_id を渡すとそのデバイスのイベントだけ（総件数もフィルタ後）
    _stub_scan(monkeypatch, [
        {"event_id": "0001-10", "onset_us": 10, "device_id": 1, "cloud_confirmed": True},
        {"event_id": "0002-20", "onset_us": 20, "device_id": 2, "cloud_confirmed": True},
        {"event_id": "0001-30", "onset_us": 30, "device_id": 1, "cloud_confirmed": True},
    ])
    items, total = events.list_page(device_id=1)
    assert _ids(items) == ["0001-30", "0001-10"] and total == 2


def test_device_filter_none_means_all(monkeypatch):
    # 無指定は全デバイス。device_id 欠落のイベント（旧データ）も落とさない
    _stub_scan(monkeypatch, [
        {"event_id": "0001-10", "onset_us": 10, "device_id": 1, "cloud_confirmed": True},
        {"event_id": "0002-20", "onset_us": 20, "device_id": 2, "cloud_confirmed": True},
        {"event_id": "0009-30", "onset_us": 30, "cloud_confirmed": True},
    ])
    items, total = events.list_page()
    assert total == 3 and len(items) == 3


def test_min_intensity_filter_uses_effective_intensity(monkeypatch):
    # 確定済みは confirmed_intensity、未確定は max_intensity で比べる。境界値は含む
    _stub_scan(monkeypatch, [
        # 速報は大きいが確定震度は小さい → 落ちる
        {"event_id": "0001-10", "onset_us": 10, "cloud_confirmed": True,
         "max_intensity": 3.0, "confirmed_intensity": 1.0},
        # 確定震度がちょうど下限 → 残る
        {"event_id": "0001-20", "onset_us": 20, "cloud_confirmed": True,
         "max_intensity": 0.1, "confirmed_intensity": 2.5},
        # 未評価(速報のみ)は max_intensity で判定 → 残る
        {"event_id": "0001-30", "onset_us": 30, "max_intensity": 2.6},
        # 震度欠落は0扱い → 落ちる
        {"event_id": "0001-40", "onset_us": 40},
    ])
    items, total = events.list_page(min_intensity=2.5)
    assert _ids(items) == ["0001-30", "0001-20"] and total == 2


def test_min_intensity_none_means_no_filter(monkeypatch):
    _stub_scan(monkeypatch, _items())
    items, total = events.list_page(min_intensity=None)
    assert total == 2


class _FakeTable:
    """DynamoDB Table の最小スタブ（get/put/scan と update: SET #n=:v と REMOVE #n のみ）。"""

    def __init__(self, page_size=1000):
        self.items: dict = {}
        self.page_size = page_size

    def scan(self, ExclusiveStartKey=None, **_):
        keys = list(self.items)
        start = keys.index(ExclusiveStartKey["event_id"]) + 1 if ExclusiveStartKey else 0
        page = keys[start:start + self.page_size]
        resp = {"Items": [dict(self.items[k]) for k in page]}
        if start + self.page_size < len(keys):
            resp["LastEvaluatedKey"] = {"event_id": page[-1]}
        return resp

    def get_item(self, Key):
        it = self.items.get(Key["event_id"])
        return {"Item": it} if it is not None else {}

    def put_item(self, Item):
        self.items[Item["event_id"]] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None):
        it = self.items.setdefault(Key["event_id"], {"event_id": Key["event_id"]})
        expr = UpdateExpression.strip()
        names = ExpressionAttributeNames or {}
        if expr.startswith("SET"):
            # "SET #n = :v" / "SET #v = :v, #s = :s" / "SET waveform_prefix = :wp"
            for assign in expr[len("SET"):].split(","):
                ph, val = (x.strip() for x in assign.split("="))
                it[names.get(ph, ph)] = ExpressionAttributeValues[val]
        elif expr.startswith("REMOVE"):
            for ph in expr[len("REMOVE"):].split(","):
                ph = ph.strip()
                it.pop(names.get(ph, ph), None)


def test_record_manual_event(monkeypatch):
    fake = _FakeTable()
    monkeypatch.setattr(events, "_table", lambda: fake)
    eid = events.record_manual_event(1, 1_000_000_000, 0.3, 0.5,
                                     waveform_prefix="events/x/", note="熊本")
    it = fake.items[eid]
    assert it["manual"] is True and it["checked"] is True
    assert it["cloud_confirmed"] is False          # 手動は自動確定ではない
    assert float(it["max_intensity"]) == 0.3
    assert it["waveform_prefix"] == "events/x/"
    assert it["note"] == "熊本"
    # 既定一覧にも出る
    _stub_scan(monkeypatch, [dict(it)])
    shown, total = events.list_page(show_all=False)
    assert total == 1


def test_record_manual_event_with_verdict(monkeypatch):
    fake = _FakeTable()
    monkeypatch.setattr(events, "_table", lambda: fake)
    eid = events.record_manual_event(1, 1_000_000_000, 0.0, 0.1, verdict="critical")
    it = fake.items[eid]
    assert it["verdict"] == "critical" and it["verdict_source"] == "human"


def test_record_manual_event_rejects_unknown_verdict(monkeypatch):
    monkeypatch.setattr(events, "_table", lambda: _FakeTable())
    with pytest.raises(ValueError):
        events.record_manual_event(1, 1_000_000_000, 0.0, 0.1, verdict="buried")


def test_set_verdict_set_and_clear(monkeypatch):
    fake = _FakeTable()
    fake.items["0001-1"] = {"event_id": "0001-1"}
    monkeypatch.setattr(events, "_table", lambda: fake)
    events.set_verdict("0001-1", "good")
    assert fake.items["0001-1"]["verdict"] == "good"
    assert fake.items["0001-1"]["verdict_source"] == "human"
    events.set_verdict("0001-1", "warning", source="auto")
    assert fake.items["0001-1"]["verdict_source"] == "auto"
    events.set_verdict("0001-1", None)
    assert "verdict" not in fake.items["0001-1"]
    assert "verdict_source" not in fake.items["0001-1"]


def test_buried_verdict_still_listed(monkeypatch):
    """完全埋没(critical)と判定したイベントも既定一覧に出す。

    「調べたが何も見えなかった」は「まだ調べていない」と区別されるべき記録なので、
    verdict では絞らない（docs/log/2026-09-06-event-verdict.md）。
    """
    fake = _FakeTable()
    monkeypatch.setattr(events, "_table", lambda: fake)
    eid = events.record_manual_event(1, 1_000_000_000, 0.0, 0.1, verdict="critical")
    _stub_scan(monkeypatch, [dict(fake.items[eid])])
    shown, total = events.list_page(show_all=False)
    assert total == 1 and shown[0]["verdict"] == "critical"


def test_set_note_set_and_clear(monkeypatch):
    fake = _FakeTable()
    fake.items["0001-1"] = {"event_id": "0001-1"}
    monkeypatch.setattr(events, "_table", lambda: fake)
    events.set_note("0001-1", "あとで見る")
    assert fake.items["0001-1"]["note"] == "あとで見る"
    events.set_note("0001-1", None)
    assert "note" not in fake.items["0001-1"]


T0 = 1_800_000_000_000_000


@pytest.fixture
def paged(monkeypatch):
    """1ページ10件で scan を区切る偽テーブル。"""
    fake = _FakeTable(page_size=10)
    monkeypatch.setattr(events, "_table", lambda: fake)
    return fake


def _seed_old_events(fake, device_id, n):
    for i in range(n):
        eid = f"{device_id:04d}-{i}"
        fake.items[eid] = {"event_id": eid, "device_id": device_id,
                           "onset_us": i, "last_us": i}


def test_continuing_shake_merges_beyond_one_scan_page(paged):
    _seed_old_events(paged, 2, 50)
    eid, is_new = events.record_device_prompt(1, T0, 0.5, 1.0)
    assert is_new
    for i in range(1, 5):
        eid2, is_new = events.record_device_prompt(1, T0 + i * 30_000_000, 0.5, 1.0)
        assert (eid2, is_new) == (eid, False)
    assert int(paged.items[eid]["last_us"]) == T0 + 4 * 30_000_000


def test_cloud_detection_joins_device_prompt_session(paged):
    _seed_old_events(paged, 1, 30)
    eid, _ = events.record_device_prompt(1, T0, 0.5, 1.0)
    eid2, _ = events.record_cloud_detection(1, T0 + 5_000_000, 0.8, 1.2)
    assert eid2 == eid
    assert paged.items[eid]["cloud_confirmed"] is True


def test_pointer_bootstraps_from_existing_events(paged):
    _seed_old_events(paged, 1, 25)
    eid, is_new = events.record_device_prompt(1, 24 + events.MERGE_GAP_US // 2, 0.5, 1.0)
    assert (eid, is_new) == ("0001-24", False)
    ptr = paged.items[events.latest_pointer_id(1)]
    assert ptr["latest_event_id"] == "0001-24"


def test_pointer_rebuilt_when_target_missing(paged):
    _seed_old_events(paged, 1, 3)
    paged.items[events.latest_pointer_id(1)] = {
        "event_id": events.latest_pointer_id(1), "latest_event_id": "0001-999"}
    eid, is_new = events.record_device_prompt(1, 2 + 1_000_000, 0.5, 1.0)
    assert (eid, is_new) == ("0001-2", False)


def test_backfilled_older_session_does_not_steal_pointer(paged):
    eid_now, _ = events.record_device_prompt(1, T0, 0.5, 1.0)
    old_onset = T0 - 3600 * 1_000_000
    eid_old, is_new = events.record_device_prompt(1, old_onset, 0.5, 1.0)
    assert is_new and eid_old != eid_now
    assert paged.items[events.latest_pointer_id(1)]["latest_event_id"] == eid_now
    eid3, is_new = events.record_device_prompt(1, T0 + 30_000_000, 0.5, 1.0)
    assert (eid3, is_new) == (eid_now, False)


def test_pointers_are_per_device(paged):
    eid1, _ = events.record_device_prompt(1, T0, 0.5, 1.0)
    eid2, is_new = events.record_device_prompt(2, T0 + 1_000_000, 0.5, 1.0)
    assert is_new and eid2 != eid1


def test_manual_event_advances_pointer_only_when_newer(paged):
    eid_now, _ = events.record_device_prompt(1, T0, 0.5, 1.0)
    events.record_manual_event(1, T0 - 86400 * 1_000_000, 0.3, 0.5)
    assert paged.items[events.latest_pointer_id(1)]["latest_event_id"] == eid_now
    eid_new = events.record_manual_event(1, T0 + 86400 * 1_000_000, 0.3, 0.5)
    assert paged.items[events.latest_pointer_id(1)]["latest_event_id"] == eid_new


def test_scans_read_all_pages_and_skip_pointers(paged):
    for i in range(25):
        events.record_device_prompt(1, T0 + i * 10 * events.MERGE_GAP_US, 0.5, 1.0)
    got = events.recent_events(limit=3)
    assert [int(e["onset_us"]) for e in got] == [
        T0 + i * 10 * events.MERGE_GAP_US for i in (24, 23, 22)]
    assert not any(events.is_pointer(e) for e in events.recent_events(limit=100))
    _, total = events.list_page(show_all=True)
    assert total == 25
