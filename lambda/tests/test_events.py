"""events.list_page のフィルタ挙動（人工地震フラグの隠し込み）。

DynamoDBに触らず、全件scanだけ差し替えてフィルタ/ソートの純粋ロジックを確認する。
"""

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


class _FakeTable:
    """DynamoDB Table の最小スタブ（get/put/update: SET #n=:v と REMOVE #n のみ）。"""

    def __init__(self):
        self.items: dict = {}

    def get_item(self, Key):
        it = self.items.get(Key["event_id"])
        return {"Item": it} if it is not None else {}

    def put_item(self, Item):
        self.items[Item["event_id"]] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None):
        it = self.items.setdefault(Key["event_id"], {"event_id": Key["event_id"]})
        name = ExpressionAttributeNames["#n"]
        if UpdateExpression.strip().startswith("SET"):
            it[name] = ExpressionAttributeValues[":v"]
        elif UpdateExpression.strip().startswith("REMOVE"):
            it.pop(name, None)


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


def test_set_note_set_and_clear(monkeypatch):
    fake = _FakeTable()
    fake.items["0001-1"] = {"event_id": "0001-1"}
    monkeypatch.setattr(events, "_table", lambda: fake)
    events.set_note("0001-1", "あとで見る")
    assert fake.items["0001-1"]["note"] == "あとで見る"
    events.set_note("0001-1", None)
    assert "note" not in fake.items["0001-1"]
