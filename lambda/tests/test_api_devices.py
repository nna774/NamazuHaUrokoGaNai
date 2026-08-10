import json
import os

import pytest

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from common import wire  # noqa: E402

from api import handler as api  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cloudwatch(monkeypatch):
    """_device()が実CloudWatchへ問い合わせないようにする（既定はデータ無し扱い）。"""
    monkeypatch.setattr(api.metrics, "latest_heap", lambda device_id: None)
    monkeypatch.setattr(api.metrics, "latest_backlog", lambda device_id: None)


def _capture_query_range(monkeypatch, items):
    captured = {}

    def fake(device_id, start_us, end_us, max_points=300):
        captured["device_id"] = device_id
        captured["start_us"] = start_us
        captured["end_us"] = end_us
        captured["max_points"] = max_points
        return items

    monkeypatch.setattr(api.device_temp, "query_range", fake)
    return captured


def _item(batch_start_us, raw, sensor_type):
    return {"device_id": 2, "batch_start_us": batch_start_us, "raw": raw, "sensor_type": sensor_type}


def _event(path, params=None):
    return {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": path,
        "queryStringParameters": params or {},
    }


def test_handler_routes_device_ids_beyond_four_digits(monkeypatch):
    """device_id は uint32 全域(最大10桁)を取りうる。sentinel値4294967295(=0xFFFFFFFF)の
    テスト機がdevices一覧には出るのに詳細だけ404になる回帰を防ぐ。"""
    device_id = 4294967295
    monkeypatch.setattr(api.devices, "get_device",
                        lambda did: {"device_id": did} if did == device_id else None)
    resp = api.handler(_event(f"/devices/{device_id}"), {})
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["device"]["device_id"] == device_id


def test_device_temp_defaults_to_three_hours(monkeypatch):
    cap = _capture_query_range(monkeypatch, [])
    monkeypatch.setattr(api.time, "time", lambda: 1000.0)
    resp = api._device_temp(2, {})
    assert resp["statusCode"] == 200
    assert cap["end_us"] == int(1000.0 * 1e6)
    assert cap["start_us"] == cap["end_us"] - int(3 * 3600 * 1e6)
    assert cap["device_id"] == 2


def test_device_temp_hours_clamped_to_max(monkeypatch):
    cap = _capture_query_range(monkeypatch, [])
    monkeypatch.setattr(api.time, "time", lambda: 1000.0)
    resp = api._device_temp(2, {"hours": "999"})
    assert cap["end_us"] - cap["start_us"] == int(api.MAX_TEMP_HOURS * 3600 * 1e6)
    assert '"hours": 24.0' in resp["body"]


def test_device_temp_bad_hours_falls_back_to_default(monkeypatch):
    cap = _capture_query_range(monkeypatch, [])
    monkeypatch.setattr(api.time, "time", lambda: 1000.0)
    api._device_temp(2, {"hours": "not-a-number"})
    assert cap["end_us"] - cap["start_us"] == int(3 * 3600 * 1e6)


def test_device_temp_reports_raw_and_celsius_for_adxl355(monkeypatch):
    _capture_query_range(monkeypatch, [_item(1000, 1900, wire.SENSOR_TYPE_ADXL355)])
    resp = api._device_temp(2, {})
    body = resp["body"]
    assert '"raw": 1900' in body
    assert '"t": 1000' in body
    assert '"c":' in body  # ADXL355なので換算値も付く


def test_device_temp_reports_raw_and_celsius_for_iis3dhhc(monkeypatch):
    _capture_query_range(monkeypatch, [_item(1000, 1900, wire.SENSOR_TYPE_IIS3DHHC)])
    resp = api._device_temp(2, {})
    body = resp["body"]
    assert '"raw": 1900' in body
    assert '"c":' in body  # IIS3DHHCも内蔵温度センサ対応済み
    assert '"c": null' not in body


def test_device_temp_passes_max_points_cap(monkeypatch):
    cap = _capture_query_range(monkeypatch, [])
    api._device_temp(2, {})
    assert cap["max_points"] == api.MAX_TEMP_POINTS


def test_device_view_reports_sensor_name(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device",
                        lambda did: {"device_id": did, "sensor_type": wire.SENSOR_TYPE_ADXL355})
    resp = api._device(2)
    assert '"sensor": "ADXL355"' in resp["body"]


def test_device_view_sensor_none_when_not_yet_recorded(monkeypatch):
    """古いデバイス台帳（device_meta導入前のデータ）は sensor_type が無い。"""
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    resp = api._device(2)
    assert '"sensor": null' in resp["body"]


def test_device_view_reports_fake_sensor_name(monkeypatch):
    """FakeSensor(結合試験用)のsensor_type=255は「未記録」と区別してダミー表示する。"""
    monkeypatch.setattr(api.devices, "get_device",
                        lambda did: {"device_id": did, "sensor_type": wire.SENSOR_TYPE_FAKE})
    resp = api._device(2)
    assert json.loads(resp["body"])["device"]["sensor"] == "ダミー"


def test_device_view_reports_uptime(monkeypatch):
    monkeypatch.setattr(api.time, "time", lambda: 2000.0)
    monkeypatch.setattr(api.devices, "get_device",
                        lambda did: {"device_id": did, "boot_epoch_us": int(1000.0 * 1e6)})
    resp = api._device(2)
    body = resp["body"]
    assert '"boot_epoch_us": 1000000000' in body
    assert '"uptime_s": 1000.0' in body


def test_device_view_uptime_none_when_not_yet_recorded(monkeypatch):
    """旧ファーム（稼働時間ヘッダ未送信）は boot_epoch_us が無い。"""
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    resp = api._device(2)
    body = resp["body"]
    assert '"boot_epoch_us": null' in body
    assert '"uptime_s": null' in body


def test_device_view_reports_reset_reason(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device",
                        lambda did: {"device_id": did, "reset_reason": "TASK_WDT"})
    resp = api._device(2)
    assert '"reset_reason": "TASK_WDT"' in resp["body"]


def test_device_view_reset_reason_none_when_not_yet_recorded(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    resp = api._device(2)
    assert '"reset_reason": null' in resp["body"]


def test_device_view_includes_heap_when_available(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    monkeypatch.setattr(api.metrics, "latest_heap", lambda did: {
        "heap_free_bytes": 123456, "heap_maxblock_bytes": 45678, "heap_measured_at_us": 999,
    })
    resp = api._device(2)
    body = resp["body"]
    assert '"heap_free_bytes": 123456' in body
    assert '"heap_maxblock_bytes": 45678' in body


def test_device_view_omits_heap_when_unavailable(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    resp = api._device(2)  # _no_cloudwatchフィクスチャによりlatest_heapはNoneを返す
    body = resp["body"]
    assert "heap_free_bytes" not in body


def test_device_view_includes_backlog_when_available(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    monkeypatch.setattr(api.metrics, "latest_backlog", lambda did: {
        "spill_count": 3, "ram_queued": 1, "backlog_measured_at_us": 999,
    })
    resp = api._device(2)
    body = resp["body"]
    assert '"spill_count": 3' in body
    assert '"ram_queued": 1' in body


def test_device_view_omits_backlog_when_unavailable(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    resp = api._device(2)  # _no_cloudwatchフィクスチャによりlatest_backlogはNoneを返す
    body = resp["body"]
    assert "spill_count" not in body


def test_device_view_reports_orientation_calibration(monkeypatch):
    from decimal import Decimal
    monkeypatch.setattr(api.devices, "get_device", lambda did: {
        "device_id": did,
        "tilt_up": [Decimal("0.01"), Decimal("-0.02"), Decimal("0.9997")],
        "tilt_deg": Decimal("0.85"),
        "azimuth_deg": Decimal("-7.9"),
        "calibration_ref_device": 1,
    })
    resp = api._device(2)
    body = resp["body"]
    assert '"tilt_up": [0.01, -0.02, 0.9997]' in body
    assert '"tilt_deg": 0.85' in body
    assert '"azimuth_deg": -7.9' in body
    assert '"calibration_ref_device": 1' in body


def test_device_view_orientation_calibration_none_when_not_yet_calibrated(monkeypatch):
    monkeypatch.setattr(api.devices, "get_device", lambda did: {"device_id": did})
    resp = api._device(2)
    body = resp["body"]
    assert '"tilt_up": null' in body
    assert '"tilt_deg": null' in body
    assert '"azimuth_deg": null' in body
    assert '"calibration_ref_device": null' in body
