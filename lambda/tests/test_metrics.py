"""metrics.record_heap / latest_heap（CloudWatchを直接叩かずFakeClientで代替する）。"""

from datetime import datetime, timedelta, timezone

import pytest

from common import metrics


class FakeCloudWatchClient:
    """put_metric_data / get_metric_statisticsだけの最小スタブ。"""

    def __init__(self):
        self.calls: list[dict] = []
        # metric_name -> [Datapoint, ...] をテスト側で仕込む
        self.datapoints: dict[str, list[dict]] = {}

    def put_metric_data(self, Namespace, MetricData):  # noqa: N803
        self.calls.append({"Namespace": Namespace, "MetricData": MetricData})

    def get_metric_statistics(self, Namespace, MetricName, Dimensions,  # noqa: N803
                               StartTime, EndTime, Period, Statistics):  # noqa: N803
        self.calls.append({"MetricName": MetricName, "Dimensions": Dimensions})
        return {"Datapoints": self.datapoints.get(MetricName, [])}


@pytest.fixture
def client(monkeypatch):
    c = FakeCloudWatchClient()
    monkeypatch.setattr(metrics, "_client", lambda: c)
    return c


def test_record_heap_sends_both_metrics_with_device_dimension(client):
    metrics.record_heap(2, 123456, 45678)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Namespace"] == metrics.NAMESPACE
    by_name = {m["MetricName"]: m for m in call["MetricData"]}
    assert set(by_name) == {"HeapFreeBytes", "HeapMaxAllocBytes"}
    assert by_name["HeapFreeBytes"]["Value"] == 123456
    assert by_name["HeapMaxAllocBytes"]["Value"] == 45678
    for m in by_name.values():
        assert m["Dimensions"] == [{"Name": "DeviceId", "Value": "2"}]
        assert m["Unit"] == "Bytes"


def test_latest_heap_returns_none_without_data(client):
    assert metrics.latest_heap(1) is None


def test_latest_heap_picks_the_newest_datapoint(client):
    now = datetime.now(timezone.utc)
    client.datapoints["HeapFreeBytes"] = [
        {"Timestamp": now - timedelta(minutes=5), "Average": 200000.0},
        {"Timestamp": now, "Average": 123456.0},  # 一番新しい
    ]
    client.datapoints["HeapMaxAllocBytes"] = [
        {"Timestamp": now, "Average": 45678.0},
    ]

    result = metrics.latest_heap(1)

    assert result["heap_free_bytes"] == 123456
    assert result["heap_maxblock_bytes"] == 45678
    assert result["heap_measured_at_us"] == int(now.timestamp() * 1e6)


def test_latest_heap_none_when_only_one_metric_has_data(client):
    client.datapoints["HeapFreeBytes"] = [
        {"Timestamp": datetime.now(timezone.utc), "Average": 100.0},
    ]
    # HeapMaxAllocBytesは未設定(空リスト扱い)

    assert metrics.latest_heap(1) is None
