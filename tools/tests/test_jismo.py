import numpy as np
import pytest

from jismo import filters, jma_fft, rounding
from jismo.fir import design_fir, DEFAULT_NUMTAPS
from jismo.realtime import RealtimeIntensity
from gen_synthetic import synth_quake, synth_noise


def test_filter_dc_is_zero():
    resp = filters.jma_filter_response(np.array([0.0]))
    assert resp[0] == 0.0


def test_highcut_unity_at_low_freq():
    # 低周波ではハイカットはほぼ1
    assert filters.highcut(np.array([0.1]))[0] == pytest.approx(1.0, abs=1e-3)


def test_highcut_attenuates_above_10hz():
    assert filters.highcut(np.array([30.0]))[0] < 0.2


def test_lowcut_attenuates_below_0_5hz():
    assert filters.lowcut(np.array([0.1]))[0] < 0.3
    assert filters.lowcut(np.array([2.0]))[0] == pytest.approx(1.0, abs=1e-2)


def test_jma_round_examples():
    # 4.678 -> 4.68 -> 4.6
    assert rounding.jma_round(4.678) == pytest.approx(4.6)
    # 境界 4.65 -> 4.65 -> 4.6
    assert rounding.jma_round(4.649) == pytest.approx(4.6)


def test_intensity_scale_boundaries():
    assert rounding.intensity_scale(0.4) == "0"
    assert rounding.intensity_scale(0.5) == "1"
    assert rounding.intensity_scale(4.9) == "5弱"
    assert rounding.intensity_scale(5.4) == "5強"
    assert rounding.intensity_scale(6.6) == "7"


def test_noise_floor_is_low_intensity():
    # 0.2 gal RMS の静置ノイズ -> 計測震度は有感(0.5)未満のはず
    data = synth_noise(100.0, 60.0, rms_gal=0.2, seed=3)
    res = jma_fft.measured_intensity(data[:, 0], data[:, 1], data[:, 2], 100.0)
    assert res.intensity < 0.5


def test_intensity_monotonic_in_amplitude():
    small = synth_quake(100.0, 60.0, amp_gal=5.0, seed=0)
    big = synth_quake(100.0, 60.0, amp_gal=50.0, seed=0)
    i_small = jma_fft.measured_intensity(small[:, 0], small[:, 1], small[:, 2], 100.0)
    i_big = jma_fft.measured_intensity(big[:, 0], big[:, 1], big[:, 2], 100.0)
    assert i_big.intensity > i_small.intensity


def test_amplitude_scaling_matches_formula():
    # 全成分を10倍すると a0 も10倍 -> I は 2*log10(10)=2.0 増える
    data = synth_quake(100.0, 60.0, amp_gal=10.0, seed=5)
    r1 = jma_fft.measured_intensity(data[:, 0], data[:, 1], data[:, 2], 100.0)
    r10 = jma_fft.measured_intensity(10 * data[:, 0], 10 * data[:, 1], 10 * data[:, 2], 100.0)
    assert r10.intensity_raw - r1.intensity_raw == pytest.approx(2.0, abs=1e-6)


def _add_ramp(data, gal_over_record):
    """記録全体で gal_over_record だけ直線的にずれるドリフトを重ねる。"""
    n = data.shape[0]
    ramp = np.linspace(0.0, gal_over_record, n)
    return data + ramp[:, None]


def test_detrend_removes_ramp():
    n = 1000
    sig = 3.0 + 0.01 * np.arange(n)
    assert np.abs(jma_fft.detrend(sig)).max() < 1e-9


def test_drift_does_not_inflate_intensity():
    """傾斜・熱ドリフトで震度が水増しされないこと（実機ADXL355で発覚）。

    Y(f) は f=0 で 0 なので直流は落ちるが傾きは落ちない。傾きが残ると
    FFTの巡回畳み込みで記録の端が繋がる際に段差ができ、そこがリンギングして
    静穏なのに震度2級の値が出る。
    """
    data = synth_noise(100.0, 120.0, rms_gal=0.2, seed=3)
    quiet = jma_fft.measured_intensity(data[:, 0], data[:, 1], data[:, 2], 100.0)
    # 重力DC(1g)＋120秒で8galのドリフト。実機で観測したのと同程度。
    drifted = _add_ramp(data, 8.0)
    drifted[:, 2] += 980.0
    res = jma_fft.measured_intensity(drifted[:, 0], drifted[:, 1], drifted[:, 2], 100.0)
    assert res.intensity < 0.5
    assert res.intensity_raw == pytest.approx(quiet.intensity_raw, abs=0.1)


def test_drift_does_not_change_quake_intensity():
    """本物の揺れの震度はドリフトの有無で変わらないこと（修正が過剰でないこと）。"""
    data = synth_quake(100.0, 90.0, amp_gal=20.0, seed=7)
    plain = jma_fft.measured_intensity(data[:, 0], data[:, 1], data[:, 2], 100.0)
    drifted = _add_ramp(data, 8.0)
    res = jma_fft.measured_intensity(drifted[:, 0], drifted[:, 1], drifted[:, 2], 100.0)
    assert res.intensity_raw == pytest.approx(plain.intensity_raw, abs=0.02)


def test_fft_and_fir_intensities_agree_on_quake():
    """FFT版とFIR版の計測震度が一致すること（tools/jismo の数値照合の本体）。"""
    for amp in (5.0, 20.0, 100.0):
        data = synth_quake(100.0, 90.0, amp_gal=amp, seed=7)
        fft = jma_fft.measured_intensity(data[:, 0], data[:, 1], data[:, 2], 100.0)
        rt = RealtimeIntensity(100.0)
        best = 0.0
        for row in data:
            rt.push(*row)
            best = max(best, rt.current_intensity())
        assert best == pytest.approx(fft.intensity, abs=0.1), f"amp={amp}"


def test_fir_composite_approximates_fft():
    # FIR版のフィルタ後合成加速度が FFT版とよく一致すること（ピーク相対誤差）
    data = synth_quake(100.0, 90.0, amp_gal=20.0, seed=7)
    ax, ay, az = data[:, 0], data[:, 1], data[:, 2]
    fft_comp = jma_fft.filtered_composite(ax, ay, az, 100.0)
    rt = RealtimeIntensity(100.0)
    fir_comp = rt.filtered_composite(ax, ay, az)
    # FIRは群遅延ぶん後ろにずれるので、遅延補正してピークを比較
    delay = (DEFAULT_NUMTAPS - 1) // 2
    fir_aligned = fir_comp[delay:]
    m = min(len(fft_comp), len(fir_aligned))
    peak_fft = fft_comp[:m].max()
    peak_fir = fir_aligned[:m].max()
    rel = abs(peak_fir - peak_fft) / peak_fft
    assert rel < 0.15, f"FIR/FFT ピーク相対誤差が大きい: {rel:.3f}"


def test_fir_taps_finite():
    taps = design_fir(100.0)
    assert np.all(np.isfinite(taps))
    assert taps.size == DEFAULT_NUMTAPS


def test_fir_dc_gain_is_zero():
    # H(0)=sum(taps) が0でないと重力DCが漏れてストリーミング震度が跳ねる（実機で発覚）
    taps = design_fir(100.0)
    assert abs(taps.sum()) < 1e-9


def test_realtime_rejects_gravity_dc():
    # z軸に重力(約1g=980gal)を乗せた静置ノイズ。リアルタイム震度は有感(0.5)未満のはず。
    rng = np.random.default_rng(0)
    n = 8000
    z = 980.0 + rng.standard_normal(n) * 0.2
    x = rng.standard_normal(n) * 0.2
    y = rng.standard_normal(n) * 0.2
    rt = RealtimeIntensity(100.0)
    max_i = 0.0
    for i in range(n):
        rt.push(x[i], y[i], z[i])
        if i % 25 == 0:
            max_i = max(max_i, rt.current_intensity())
    assert max_i < 0.5, max_i
