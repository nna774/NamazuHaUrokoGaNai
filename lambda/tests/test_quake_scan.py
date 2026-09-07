"""quake_scan の純粋関数（重複排除・失敗検知）のテスト。

ota_watch.evaluate_ota_stuck と同じ形の状態遷移テスト。しきい値
stuck=32時間, 再送=1日を基準にする。
"""

from common import quake_scan

STUCK = 32 * 3600 * 1_000_000     # 32時間[us]
RENOTIFY = 86_400_000_000          # 1日[us]
NOW = 1_000_000_000_000            # 適当な現在時刻[us]


def test_filter_new_keeps_unnotified_only():
    assert quake_scan.filter_new(["a", "b", "c"], {"b"}) == ["a", "c"]


def test_filter_new_empty_when_all_notified():
    assert quake_scan.filter_new(["a", "b"], {"a", "b"}) == []


def test_filter_new_preserves_order():
    assert quake_scan.filter_new(["c", "a", "b"], set()) == ["c", "a", "b"]


def _state(success_ago_us=None, stuck_notified_ago_us=None):
    st = {}
    if success_ago_us is not None:
        st["last_success_at_us"] = NOW - success_ago_us
    if stuck_notified_ago_us is not None:
        st["stuck_notified_at_us"] = NOW - stuck_notified_ago_us
    return st


def test_never_run_stays_quiet():
    # last_success_at_us が無い(デプロイ直後・未実行) → 誤検知しない
    assert quake_scan.evaluate_stuck({}, NOW, STUCK, RENOTIFY) is None


def test_recently_succeeded_stays_quiet():
    it = _state(success_ago_us=3600_000_000)  # 1時間前
    assert quake_scan.evaluate_stuck(it, NOW, STUCK, RENOTIFY) is None


def test_first_stuck():
    it = _state(success_ago_us=33 * 3600 * 1_000_000)  # 33時間前(32時間超過)
    assert quake_scan.evaluate_stuck(it, NOW, STUCK, RENOTIFY) == "stuck"


def test_stuck_but_recently_notified_stays_quiet():
    it = _state(success_ago_us=2 * 86_400_000_000, stuck_notified_ago_us=3_600_000_000)
    assert quake_scan.evaluate_stuck(it, NOW, STUCK, RENOTIFY) is None


def test_stuck_renotify_after_a_day():
    it = _state(success_ago_us=3 * 86_400_000_000, stuck_notified_ago_us=86_400_000_000 + 1)
    assert quake_scan.evaluate_stuck(it, NOW, STUCK, RENOTIFY) == "stuck_again"
