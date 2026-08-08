"""device_meta.record_sensor_type / record_boot_epoch
（DynamoDB を直接叩かず FakeTable で代替する）。
"""

import re

import pytest

from common import device_meta

_SET_FIELD = re.compile(r"(\w+) = (:\w+)")


class FakeTable:
    """update_item だけの最小スタブ。"SET a = :x, b = :y, ..." 形式のSET式だけ拾えれば十分。"""

    def __init__(self):
        self.items: dict[int, dict] = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):  # noqa: N803
        device_id = Key["device_id"]
        item = self.items.setdefault(device_id, {"device_id": device_id})
        assert UpdateExpression.startswith("SET "), f"unsupported UpdateExpression: {UpdateExpression}"
        fields = _SET_FIELD.findall(UpdateExpression)
        assert fields, f"unsupported UpdateExpression: {UpdateExpression}"
        for field, placeholder in fields:
            item[field] = ExpressionAttributeValues[placeholder]


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(device_meta, "_table", lambda: t)
    return t


def test_record_sensor_type_writes_value(table):
    device_meta.record_sensor_type(2, 1)
    assert table.items[2]["sensor_type"] == 1


def test_record_sensor_type_overwrites_on_resend(table):
    device_meta.record_sensor_type(2, 1)
    device_meta.record_sensor_type(2, 1)  # 同じ値の再送でも壊れない
    assert table.items[2]["sensor_type"] == 1


def test_record_boot_epoch_writes_value(table):
    device_meta.record_boot_epoch(2, 1_700_000_000_000_000)
    assert table.items[2]["boot_epoch_us"] == 1_700_000_000_000_000


def test_record_boot_epoch_without_reset_reason_does_not_write_field(table):
    # 旧ファーム等、X-Namz-Reset-Reasonヘッダが無い場合は前回値を消さないよう
    # フィールド自体を書かない。
    device_meta.record_boot_epoch(2, 1_700_000_000_000_000)
    assert "reset_reason" not in table.items[2]


def test_record_boot_epoch_writes_reset_reason(table):
    device_meta.record_boot_epoch(2, 1_700_000_000_000_000, reset_reason="TASK_WDT")
    assert table.items[2]["boot_epoch_us"] == 1_700_000_000_000_000
    assert table.items[2]["reset_reason"] == "TASK_WDT"


def test_should_update_boot_epoch_true_when_unset():
    assert device_meta.should_update_boot_epoch(None, 1_000_000) is True


def test_should_update_boot_epoch_false_within_threshold():
    # TimeSyncのジッタ程度(±30秒 = 30_000_000us)は同一ブートセッションとみなし書き込まない
    assert device_meta.should_update_boot_epoch(1_000_000_000, 1_000_000_000 + 30_000_000) is False


def test_should_update_boot_epoch_true_beyond_threshold():
    # ±2分を超えるズレ = 再起動とみなす
    over = device_meta.BOOT_EPOCH_DRIFT_THRESHOLD_US + 1
    assert device_meta.should_update_boot_epoch(1_000_000_000, 1_000_000_000 + over) is True


def test_should_update_boot_epoch_handles_negative_drift():
    over = device_meta.BOOT_EPOCH_DRIFT_THRESHOLD_US + 1
    assert device_meta.should_update_boot_epoch(1_000_000_000, 1_000_000_000 - over) is True
