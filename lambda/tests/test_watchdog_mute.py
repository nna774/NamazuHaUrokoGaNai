"""watchdog_mute.is_muted の純粋関数テスト（devices.evaluateと同じ考え方）。"""

from common import watchdog_mute


def test_unmuted_by_default():
    assert watchdog_mute.is_muted({"device_id": 1}) is False


def test_muted_when_flag_true():
    assert watchdog_mute.is_muted({"device_id": 1, "watchdog_muted": True}) is True


def test_not_muted_when_flag_false():
    # DynamoDBのBOOLで明示的にFalseが入っている場合も無視扱いにしない
    assert watchdog_mute.is_muted({"device_id": 1, "watchdog_muted": False}) is False


def test_clear_mute_fragment_returns_remove_expression():
    expr, values = watchdog_mute.clear_mute_fragment()
    assert expr == "REMOVE watchdog_muted"
    assert values == {}
