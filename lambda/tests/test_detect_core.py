import sys
import os

import numpy as np
import pytest

# gen_synthetic は tools/ にある
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "tools")))
from gen_synthetic import synth_quake, synth_noise  # noqa: E402

from common import detect_core  # noqa: E402


def test_quake_is_detected():
    data = synth_quake(100.0, 120.0, amp_gal=20.0, seed=1)
    det = detect_core.analyze(data, 100.0, window_start_us=1_000_000, threshold=0.5)
    assert det is not None
    assert det.max_intensity >= 1.0
    # onset は揺れの立ち上がり（先頭付近ではなく包絡の立ち上がり）にある
    assert det.onset_us > 1_000_000


def test_noise_floor_not_detected():
    data = synth_noise(100.0, 120.0, rms_gal=0.2, seed=2)
    det = detect_core.analyze(data, 100.0, window_start_us=0, threshold=0.5)
    assert det is None


def test_single_spike_not_detected():
    # 生活振動: 0.1秒だけの単発スパイク -> 継続条件で落ちる
    data = synth_noise(100.0, 60.0, rms_gal=0.05, seed=3)
    data[3000:3010, :] += 50.0  # 0.1秒だけ大振幅
    det = detect_core.analyze(data, 100.0, window_start_us=0,
                              threshold=0.5, hold_seconds=2.0)
    assert det is None


def test_amp_for_intensity_inverse():
    # amp_for_intensity は I=2log10(a)+0.94 の逆関数
    a = detect_core.amp_for_intensity(2.0)
    assert 2.0 * np.log10(a) + 0.94 == pytest.approx(2.0, abs=1e-9)
