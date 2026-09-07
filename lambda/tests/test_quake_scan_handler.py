"""quake_scan Lambdaの配線テスト（DynamoDB/Slack/気象庁JSONは全てモック）。

候補抽出(scan_quakes)・重複排除(common.quake_scan)・通知(batch_uplink.notify)を
正しくつなげているかを見る。各モジュール自体の判定ロジックは
tools/tests/test_scan_quakes.py・test_quake_scan.pyで別途テスト済み。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from batch_uplink import notify

from common import quake_scan
from quake_scan import handler as qs


def _entry(eid, hours_ago, anm, lat, lon, depth_m, mag):
    sign = lambda v: f"+{v}" if v >= 0 else f"{v}"
    at = (datetime.now(qs.JST) - timedelta(hours=hours_ago)).isoformat()
    return {
        "eid": eid, "at": at, "anm": anm,
        "cod": f"{sign(lat)}{sign(lon)}{sign(depth_m)}/",
        "mag": str(mag), "maxi": "1",
    }


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, body, fields):
        self.calls.append((title, body, fields))


@pytest.fixture(autouse=True)
def _wire_fakes(monkeypatch):
    monkeypatch.setattr(qs, "fetch_list", lambda: qs_entries["value"])
    monkeypatch.setattr(quake_scan, "get_notified_eids", lambda eids: qs_notified["value"])
    monkeypatch.setattr(quake_scan, "mark_notified", lambda eids, at_us: marked.append((eids, at_us)))
    monkeypatch.setattr(quake_scan, "mark_success", lambda at_us: succeeded.append(at_us))
    monkeypatch.setattr(notify, "from_env", lambda: fake_notifier)


qs_entries = {"value": []}
qs_notified = {"value": set()}
marked: list = []
succeeded: list = []
fake_notifier = FakeNotifier()


@pytest.fixture(autouse=True)
def _reset_state():
    qs_entries["value"] = []
    qs_notified["value"] = set()
    marked.clear()
    succeeded.clear()
    fake_notifier.calls.clear()
    yield


# 「投げる価値あり」ゾーンに入る座標・マグニチュード（既存fixtureイベントに近い値）
WORTH_ASKING = dict(lat=37.3, lon=141.2, depth_m=-60000, mag=4.0)
# 「遠すぎ」かつ通知閾値(M4.0)未満——通知されないはず
FAR_TOO_SMALL = dict(lat=24.0, lon=124.0, depth_m=-10000, mag=3.0)


def test_notifies_new_worth_asking_candidate():
    qs_entries["value"] = [_entry("e1", 1, "テスト震源", **WORTH_ASKING)]
    result = qs.handler({}, None)

    assert result["new"] == 1
    assert len(fake_notifier.calls) == 1
    title, body, fields = fake_notifier.calls[0]
    assert "1件" in title
    assert "テスト震源" in body
    assert "detectlab.py" in body
    assert qs.SLACK_MENTION in body  # 0件でない時は見逃し防止でメンションを付ける
    assert marked == [(["e1"], succeeded[0])]
    assert len(succeeded) == 1


def test_far_zone_below_threshold_is_not_notified():
    qs_entries["value"] = [_entry("e2", 1, "遠い小さい地震", **FAR_TOO_SMALL)]
    result = qs.handler({}, None)

    assert result["new"] == 0
    title, body, _ = fake_notifier.calls[0]
    assert body == "新規候補なし。"
    assert qs.SLACK_MENTION not in body  # 0件の時はメンション無し
    # 成功記録は候補の有無に関わらず必ず行う（watchdogの停滞検知が読むため）
    assert len(succeeded) == 1
    assert marked == []


def test_already_notified_eid_is_skipped():
    qs_entries["value"] = [_entry("e1", 1, "テスト震源", **WORTH_ASKING)]
    qs_notified["value"] = {"e1"}
    result = qs.handler({}, None)

    assert result["new"] == 0
    assert marked == []


def test_saturday_digest_includes_threshold_reminder(monkeypatch):
    class FixedSaturday(datetime):
        @classmethod
        def now(cls, tz=None):
            # 2026-09-12は土曜日
            return cls(2026, 9, 12, 9, 0, tzinfo=tz)

    monkeypatch.setattr(qs.dt, "datetime", FixedSaturday)
    qs_entries["value"] = []
    qs.handler({}, None)

    _, body, _ = fake_notifier.calls[0]
    assert "閾値を見直してもいいかも" in body
