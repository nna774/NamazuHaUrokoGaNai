import os

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from common import wire  # noqa: E402

from api import handler as api  # noqa: E402


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


def test_device_temp_omits_celsius_for_unsupported_sensor(monkeypatch):
    _capture_query_range(monkeypatch, [_item(1000, 1900, wire.SENSOR_TYPE_IIS3DHHC)])
    resp = api._device_temp(2, {})
    assert '"c": null' in resp["body"]


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
