"""device_meta.record_sensor_type（DynamoDB を直接叩かず FakeTable で代替する）。"""

import pytest

from common import device_meta


class FakeTable:
    """update_item だけの最小スタブ。SET式の右辺の値だけ拾えれば十分。"""

    def __init__(self):
        self.items: dict[int, dict] = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):  # noqa: N803
        device_id = Key["device_id"]
        item = self.items.setdefault(device_id, {"device_id": device_id})
        assert UpdateExpression == "SET sensor_type = :s"
        item["sensor_type"] = ExpressionAttributeValues[":s"]


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
