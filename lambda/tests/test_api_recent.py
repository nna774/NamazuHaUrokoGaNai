import os

import numpy as np

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from api import handler as api  # noqa: E402


def _capture_load_window(monkeypatch):
    """store.load_window の呼び出し引数を捕捉し、空波形を返すスタブに差し替える。"""
    captured = {}

    def fake(s3, bucket, end_us, seconds):
        captured["end_us"] = end_us
        captured["seconds"] = seconds
        return np.empty((0, 3)), end_us, 100.0

    monkeypatch.setattr(api.store, "load_window", fake)
    return captured


def test_recent_start_builds_forward_window(monkeypatch):
    cap = _capture_load_window(monkeypatch)
    start_us = 1_000_000_000_000
    resp = api._recent({"minutes": "5", "start": str(start_us)})
    assert resp["statusCode"] == 200
    # start 指定は [start, start+minutes] を要求する → 終端 = start + 5分
    assert cap["end_us"] == start_us + int(5 * 60 * 1e6)
    assert cap["seconds"] == 5 * 60


def test_recent_without_start_uses_now(monkeypatch):
    cap = _capture_load_window(monkeypatch)
    monkeypatch.setattr(api.time, "time", lambda: 2000.0)
    resp = api._recent({"minutes": "1"})
    assert resp["statusCode"] == 200
    # 無指定は now を終端に直近 minutes 分
    assert cap["end_us"] == int(2000.0 * 1e6)
    assert cap["seconds"] == 60


def test_recent_bad_start_falls_back_to_now(monkeypatch):
    cap = _capture_load_window(monkeypatch)
    monkeypatch.setattr(api.time, "time", lambda: 3000.0)
    resp = api._recent({"minutes": "1", "start": "not-a-number"})
    assert resp["statusCode"] == 200
    assert cap["end_us"] == int(3000.0 * 1e6)
