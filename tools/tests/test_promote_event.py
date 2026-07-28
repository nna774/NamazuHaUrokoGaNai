import datetime
import zoneinfo

import pytest

import promote_event


def test_parse_jst():
    us = promote_event.parse_jst("2026-07-28 16:29:00")
    dt = datetime.datetime.fromtimestamp(us / 1e6, zoneinfo.ZoneInfo("Asia/Tokyo"))
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2026, 7, 28, 16, 29, 0)
    with pytest.raises(SystemExit):
        promote_event.parse_jst("not-a-time")


def test_batch_start_and_device_from_key():
    key = "raw/2026/07/28/16/0001-00000001719555000000.bin"
    assert promote_event._device_of(key) == 1
    assert promote_event._batch_start_of(key) == 1719555000000
    assert promote_event._batch_start_of("raw/2026/07/28/16/bogus.bin") is None


def test_resolve_bucket_env(monkeypatch):
    monkeypatch.setenv("NAMZ_BUCKET", "namz-data-test")
    assert promote_event.resolve_bucket(None) == "namz-data-test"
    assert promote_event.resolve_bucket("explicit") == "explicit"
