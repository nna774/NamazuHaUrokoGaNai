"""metrics.record_heap（CloudWatchを直接叩かずFakeClientで代替する）。"""

import pytest

from common import metrics


class FakeCloudWatchClient:
    """put_metric_dataだけの最小スタブ。"""

    def __init__(self):
        self.calls: list[dict] = []

    def put_metric_data(self, Namespace, MetricData):  # noqa: N803
        self.calls.append({"Namespace": Namespace, "MetricData": MetricData})


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
