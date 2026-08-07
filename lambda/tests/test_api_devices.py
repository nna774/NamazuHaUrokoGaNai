import os

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from common import wire  # noqa: E402

from api import handler as api  # noqa: E402


def _capture_load_temp_series(monkeypatch, series):
    captured = {}

    def fake(s3, bucket, end_us, seconds, device_id, max_points=300):
        captured["end_us"] = end_us
        captured["seconds"] = seconds
        captured["device_id"] = device_id
        captured["max_points"] = max_points
        return series

    monkeypatch.setattr(api.store, "load_temp_series", fake)
    return captured


def _meta(sensor_type, raw):
    return wire.BatchMeta(
        version=2, sensor_type=sensor_type, sample_format=0, axes=3,
        batch_start_us=0, sample_rate_hz=100.0, sample_count=1,
        scale_mg_per_lsb=1.0, device_id=2,
        trailer={wire.TRAILER_SENSOR_TEMP: raw.to_bytes(2, "little")},
    )


def test_device_temp_defaults_to_three_hours(monkeypatch):
    cap = _capture_load_temp_series(monkeypatch, [])
    monkeypatch.setattr(api.time, "time", lambda: 1000.0)
    resp = api._device_temp(2, {})
    assert resp["statusCode"] == 200
    assert cap["end_us"] == int(1000.0 * 1e6)
    assert cap["seconds"] == 3 * 3600
    assert cap["device_id"] == 2


def test_device_temp_hours_clamped_to_max(monkeypatch):
    cap = _capture_load_temp_series(monkeypatch, [])
    api._device_temp(2, {"hours": "999"})
    assert cap["seconds"] == api.MAX_TEMP_HOURS * 3600


def test_device_temp_bad_hours_falls_back_to_default(monkeypatch):
    cap = _capture_load_temp_series(monkeypatch, [])
    api._device_temp(2, {"hours": "not-a-number"})
    assert cap["seconds"] == 3 * 3600


def test_device_temp_reports_raw_and_celsius_for_adxl355(monkeypatch):
    series = [(1000, _meta(wire.SENSOR_TYPE_ADXL355, 1900))]
    _capture_load_temp_series(monkeypatch, series)
    resp = api._device_temp(2, {})
    body = resp["body"]
    assert '"raw": 1900' in body
    assert '"t": 1000' in body
    assert '"c":' in body  # ADXL355なので換算値も付く


def test_device_temp_omits_celsius_for_unsupported_sensor(monkeypatch):
    series = [(1000, _meta(wire.SENSOR_TYPE_IIS3DHHC, 1900))]
    _capture_load_temp_series(monkeypatch, series)
    resp = api._device_temp(2, {})
    assert '"c": null' in resp["body"]
