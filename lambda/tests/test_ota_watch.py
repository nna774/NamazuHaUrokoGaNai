"""ota_watch.evaluate_ota_stuck の停滞状態遷移（docs/ota.md §7）。

devices.evaluate（欠測判定）と同じ形の純粋関数テスト。しきい値
stuck=30分, 再送=1日を基準にする。
"""

from common import ota_watch

STUCK = 1_800_000_000        # 30分[us]
RENOTIFY = 86_400_000_000    # 1日[us]
NOW = 1_000_000_000_000      # 適当な現在時刻[us]


def _item(requested_ago_us=None, notified_ago_us=None, version="a1b2c3d"):
    it = {"device_id": 2}
    if version:
        it["pending_ota_version"] = version
    if requested_ago_us is not None:
        it["pending_ota_requested_at_us"] = NOW - requested_ago_us
    if notified_ago_us is not None:
        it["ota_stuck_notified_at_us"] = NOW - notified_ago_us
    return it


def test_no_pending_no_action():
    # 許可自体が無い → 何もしない
    assert ota_watch.evaluate_ota_stuck(_item(version=None), NOW, STUCK, RENOTIFY) is None


def test_recently_requested_stays_quiet():
    # 要求してからまだ日が浅い → 黙る（バックオフでのリトライ中かもしれない）
    it = _item(requested_ago_us=60_000_000)  # 1分前
    assert ota_watch.evaluate_ota_stuck(it, NOW, STUCK, RENOTIFY) is None


def test_first_stuck():
    # しきい値超え・未通知 → 初回通知
    it = _item(requested_ago_us=2_000_000_000)  # 33分強前
    assert ota_watch.evaluate_ota_stuck(it, NOW, STUCK, RENOTIFY) == "stuck"


def test_stuck_but_recently_notified_stays_quiet():
    # 停滞継続中だが再送間隔前 → 黙る
    it = _item(requested_ago_us=2 * 86_400_000_000, notified_ago_us=3_600_000_000)
    assert ota_watch.evaluate_ota_stuck(it, NOW, STUCK, RENOTIFY) is None


def test_stuck_renotify_after_a_day():
    # 停滞継続・前回通知から1日以上 → 再送
    it = _item(requested_ago_us=3 * 86_400_000_000, notified_ago_us=86_400_000_000 + 1)
    assert ota_watch.evaluate_ota_stuck(it, NOW, STUCK, RENOTIFY) == "stuck_again"


def test_pending_without_timestamp_is_ignored():
    # pending_ota_versionだけあってpending_ota_requested_at_usが無い
    # （手動でDynamoDBを触った等、想定外の状態）→ 誤検知しない
    it = {"device_id": 2, "pending_ota_version": "a1b2c3d"}
    assert ota_watch.evaluate_ota_stuck(it, NOW, STUCK, RENOTIFY) is None
