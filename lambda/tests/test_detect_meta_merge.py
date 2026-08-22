"""_merge_meta: 弱い再発火が meta.json の強い記録を上書きしないことの確認。

M5.9地震の事後解析(2026-08-23)で、セッション後半の弱いcoda再発火が meta.json を
弱い値(max_intensity=0.8)で上書きし、本来の最大値(2.6/2.7)が消えていたのを見つけた。
"""

import os

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from detect import handler as detect  # noqa: E402


def test_no_prev_meta_passes_through():
    onset, intensity, peak, a0 = detect._merge_meta(None, 100, 2.7, 1.2, 0.9)
    assert (onset, intensity, peak, a0) == (100, 2.7, 1.2, 0.9)


def test_weaker_retrigger_does_not_regress_recorded_max():
    prev = {"onset_us": 100, "max_intensity": 2.7, "peak_gal": 1.2, "a0_gal": 0.9}
    onset, intensity, peak, a0 = detect._merge_meta(prev, 200, 0.8, 0.3, 0.2)
    assert (onset, intensity, peak, a0) == (100, 2.7, 1.2, 0.9)


def test_stronger_retrigger_updates_max():
    prev = {"onset_us": 100, "max_intensity": 0.8, "peak_gal": 0.3, "a0_gal": 0.2}
    onset, intensity, peak, a0 = detect._merge_meta(prev, 150, 2.7, 1.2, 0.9)
    assert (onset, intensity, peak, a0) == (100, 2.7, 1.2, 0.9)


def test_onset_keeps_earliest():
    prev = {"onset_us": 100, "max_intensity": 1.0, "peak_gal": 0.5}
    onset, *_ = detect._merge_meta(prev, 50, 0.5, 0.2, None)
    assert onset == 50


def test_a0_missing_from_prev_and_call_stays_none():
    prev = {"onset_us": 100, "max_intensity": 1.0, "peak_gal": 0.5}
    _, _, _, a0 = detect._merge_meta(prev, 100, 1.0, 0.5, None)
    assert a0 is None
