"""devices.evaluate の欠測状態遷移。

DynamoDBに触れず、純粋な判定ロジック（オンライン→欠測→再送→復帰）だけ確認する。
時刻はすべて us。しきい値 offline=5分, 再送=1日 を基準にする。
"""

from common import devices

OFFLINE = 300_000_000        # 5分[us]
RENOTIFY = 86_400_000_000    # 1日[us]
NOW = 1_000_000_000_000      # 適当な現在時刻[us]


def _item(last_ingest_ago_us, notified_ago_us=None):
    it = {"device_id": 1, "last_ingest_at_us": NOW - last_ingest_ago_us}
    if notified_ago_us is not None:
        it["offline_notified_at_us"] = NOW - notified_ago_us
    return it


def test_online_no_action():
    # 直近に受信あり・未通知 → 何もしない
    assert devices.evaluate(_item(60_000_000), NOW, OFFLINE, RENOTIFY) is None


def test_first_offline():
    # しきい値超え・未通知 → 初回欠測通知
    assert devices.evaluate(_item(400_000_000), NOW, OFFLINE, RENOTIFY) == "offline"


def test_offline_but_recently_notified_stays_quiet():
    # 欠測継続中だが再送間隔前 → 黙る
    it = _item(2 * 86_400_000_000, notified_ago_us=3_600_000_000)  # 1時間前に通知
    assert devices.evaluate(it, NOW, OFFLINE, RENOTIFY) is None


def test_offline_renotify_after_a_day():
    # 欠測継続・前回通知から1日以上 → 再送
    it = _item(3 * 86_400_000_000, notified_ago_us=86_400_000_000 + 1)
    assert devices.evaluate(it, NOW, OFFLINE, RENOTIFY) == "offline_again"


def test_recovery_after_notified():
    # 通知済みだが受信が復活（経過がしきい値以内） → 復帰
    it = _item(30_000_000, notified_ago_us=2 * 86_400_000_000)
    assert devices.evaluate(it, NOW, OFFLINE, RENOTIFY) == "recovery"


def test_online_and_never_notified_stays_none():
    it = _item(30_000_000)
    assert devices.evaluate(it, NOW, OFFLINE, RENOTIFY) is None


def test_staleness_no_record_returns_now():
    # 未受信(記録なし)は now をそのまま返す（= 巨大な経過 → 欠測扱い）
    assert devices.staleness_us({}, NOW) == NOW
