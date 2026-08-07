"""device_temp の記録・照会（DynamoDB を直接叩かず FakeTable で代替する）。"""

import pytest

from common import device_temp


class FakeTable:
    """put_item / query だけの最小スタブ。KeyConditionExpression は評価しない
    （テスト側で用意した Key 条件をそのまま再現できるほど複雑にする価値がないので、
    device_id と between 範囲だけを Python 側で素直にフィルタする）。
    """

    def __init__(self):
        self.items: list[dict] = []
        self.query_calls = 0

    def put_item(self, Item):  # noqa: N803
        # device_id+batch_start_us が同じなら上書き（実テーブルの主キー衝突と同じ）
        key = (Item["device_id"], Item["batch_start_us"])
        self.items = [it for it in self.items
                     if (it["device_id"], it["batch_start_us"]) != key]
        self.items.append(dict(Item))

    def query(self, KeyConditionExpression, ExclusiveStartKey=None):  # noqa: N803
        self.query_calls += 1
        cond = KeyConditionExpression
        # boto3.dynamodb.conditions の内部表現から device_id/between の値を拾う。
        # Equals._values = (Key, value) / Between._values = (Key, lo, hi)。
        device_id = cond._values[0]._values[1]
        lo, hi = cond._values[1]._values[1], cond._values[1]._values[2]
        matched = [it for it in self.items
                  if it["device_id"] == device_id and lo <= it["batch_start_us"] <= hi]
        return {"Items": matched}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(device_temp, "_table", lambda: t)
    return t


def test_record_writes_expected_fields(table):
    device_temp.record(2, 1000, raw=1900, sensor_type=1)
    assert len(table.items) == 1
    it = table.items[0]
    assert it["device_id"] == 2
    assert it["batch_start_us"] == 1000
    assert it["raw"] == 1900
    assert it["sensor_type"] == 1
    assert "ttl" in it


def test_record_is_idempotent_on_same_key(table):
    device_temp.record(2, 1000, raw=1900, sensor_type=1)
    device_temp.record(2, 1000, raw=1950, sensor_type=1)  # 同じキーへの再送
    assert len(table.items) == 1
    assert table.items[0]["raw"] == 1950  # 後勝ち（実テーブルの上書きと同じ）


def test_query_range_filters_by_device_and_time(table):
    device_temp.record(1, 500, raw=1800, sensor_type=0)
    device_temp.record(2, 1000, raw=1900, sensor_type=1)
    device_temp.record(2, 2000, raw=1901, sensor_type=1)
    device_temp.record(2, 5000, raw=1902, sensor_type=1)  # 窓の外
    out = device_temp.query_range(2, 900, 3000)
    assert [it["batch_start_us"] for it in out] == [1000, 2000]


def test_query_range_sorts_by_time(monkeypatch):
    t = FakeTable()
    t.items = [
        {"device_id": 2, "batch_start_us": 3000, "raw": 3, "sensor_type": 1},
        {"device_id": 2, "batch_start_us": 1000, "raw": 1, "sensor_type": 1},
        {"device_id": 2, "batch_start_us": 2000, "raw": 2, "sensor_type": 1},
    ]
    monkeypatch.setattr(device_temp, "_table", lambda: t)
    out = device_temp.query_range(2, 0, 4000)
    assert [it["batch_start_us"] for it in out] == [1000, 2000, 3000]


def test_query_range_subsamples_to_max_points(monkeypatch):
    t = FakeTable()
    for i in range(20):
        t.items.append({"device_id": 2, "batch_start_us": i * 1000,
                        "raw": 1900 + i, "sensor_type": 1})
    monkeypatch.setattr(device_temp, "_table", lambda: t)
    out = device_temp.query_range(2, 0, 20000, max_points=5)
    assert len(out) <= 5
    assert len(out) >= 1
    # 間引いても時刻順であること
    assert out == sorted(out, key=lambda it: it["batch_start_us"])
