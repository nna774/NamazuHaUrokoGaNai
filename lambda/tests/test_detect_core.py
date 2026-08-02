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


def test_drifting_noise_not_detected():
    """ドリフトのある静穏窓で誤検知しないこと（実機ADXL355の据え付け前データで発覚）。

    120秒で8gal傾く＋z軸に重力1g。修正前はフィルタ後合成が端で4gal級に暴れ、
    peak_gal と震度が実体の8倍に膨れていた。
    """
    data = synth_noise(100.0, 120.0, rms_gal=0.2, seed=4)
    data += np.linspace(0.0, 8.0, data.shape[0])[:, None]
    data[:, 2] += 980.0
    assert detect_core.analyze(data, 100.0, window_start_us=0, threshold=0.5) is None


def test_quake_survives_drift():
    """ドリフトが乗っても本物の揺れは検知され、震度が動かないこと。"""
    data = synth_quake(100.0, 120.0, amp_gal=20.0, seed=1)
    plain = detect_core.analyze(data, 100.0, window_start_us=0, threshold=0.5)
    drifted = data + np.linspace(0.0, 8.0, data.shape[0])[:, None]
    drifted[:, 2] += 980.0
    det = detect_core.analyze(drifted, 100.0, window_start_us=0, threshold=0.5)
    assert det is not None
    assert det.max_intensity == pytest.approx(plain.max_intensity, abs=0.1)


def test_core_slice_keeps_short_windows_whole():
    # 端を落とすと評価するものが無くなる短い窓では落とさない
    assert detect_core.core_slice(300, 100.0) == slice(0, 300)
    assert detect_core.core_slice(12000, 100.0) == slice(500, 11500)


def test_stride_zero_evaluates_every_batch():
    # 既定(0)は間引きなし。バッチ長がいくらでも常に担当する
    for start in (0, 1_000_000, 15_000_000, 999_999_999):
        assert detect_core.crosses_stride(start, start + 15_000_000, 0.0)


def test_stride_halves_15s_batches():
    """15秒バッチ・stride 30秒でちょうど2回に1回になる（絶対時刻の格子で決まる）。"""
    hits = [detect_core.crosses_stride(i * 15_000_000, (i + 1) * 15_000_000, 30.0)
            for i in range(8)]
    assert hits == [False, True, False, True, False, True, False, True]


def test_stride_does_not_thin_when_batch_is_long_enough():
    # batch_len >= stride なら全バッチが境界を跨ぐ = 劣化しない
    for i in range(8):
        assert detect_core.crosses_stride(i * 30_000_000, (i + 1) * 30_000_000, 30.0)
    # 格子に揃っていないバッチでも同じ（30秒進めば必ずどこかの境界を越える）
    for i in range(8):
        s = 7_123_456 + i * 30_000_000
        assert detect_core.crosses_stride(s, s + 30_000_000, 30.0)


def test_stride_skips_batch_with_no_new_span():
    # 長さ0のバッチは新しい時間を持たないので担当しない
    assert not detect_core.crosses_stride(30_000_000, 30_000_000, 30.0)


def test_clamp_stride_limits_to_effective_window():
    # 実効窓長 = 120 - 2*5 = 110 を超える刻みは取りこぼしになるので切り詰める
    assert detect_core.clamp_stride(200.0, 120.0) == 110.0
    assert detect_core.clamp_stride(30.0, 120.0) == 30.0
    assert detect_core.clamp_stride(0.0, 120.0) == 0.0
    assert detect_core.clamp_stride(-5.0, 120.0) == 0.0
    # 端を落とす余裕も無い短い窓では間引かない方向に倒す
    assert detect_core.clamp_stride(30.0, 5.0) == 0.0


def test_amp_for_intensity_inverse():
    # amp_for_intensity は I=2log10(a)+0.94 の逆関数
    a = detect_core.amp_for_intensity(2.0)
    assert 2.0 * np.log10(a) + 0.94 == pytest.approx(2.0, abs=1e-9)
