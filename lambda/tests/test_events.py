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
