import numpy as np
import pytest

import calibrate_orientation as calib

FS = 100.0
G = 980.0


def _tap_burst(t, amp_gal=50.0, freq_hz=8.0, tau_s=0.15):
    """タップ直後の減衰振動(t<0では0)。"""
    burst = amp_gal * np.exp(-np.clip(t, 0, None) / tau_s) * np.sin(2 * np.pi * freq_hz * t)
    return np.where(t >= 0, burst, 0.0)


def _flat_device(eid, onset_idx=300, n=400, angle_deg=0.0, amp_gal=50.0, lag_samples=0):
    """傾き0(up=[0,0,1])で、指定した水平方位角に沿ってタップした合成波形。"""
    t_rel = (np.arange(n) - onset_idx + lag_samples) / FS
    burst = _tap_burst(t_rel, amp_gal=amp_gal)
    x = burst * np.cos(np.radians(angle_deg))
    y = burst * np.sin(np.radians(angle_deg))
    gal = np.stack([x, y, np.full(n, G)], axis=1)
    onset_us = int(round(onset_idx / FS * 1e6))
    return calib.DeviceCal(eid, calib.device_of(eid), onset_us, gal, start_us=0, fs=FS)


def test_frame_from_up_is_orthonormal():
    for up in ([0.0, 0.0, 1.0], [0.1, 0.2, 0.97], [0.99, 0.05, 0.13]):
        up = np.array(up) / np.linalg.norm(up)
        R = calib.frame_from_up(up)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)
        np.testing.assert_allclose(R[2], up, atol=1e-9)


def test_frame_from_up_switches_reference_when_up_near_x_axis():
    # up が raw frame の X 軸に近いと、既定の ref=[1,0,0] は使えない(射影がほぼ0になる)。
    up = np.array([0.95, 0.05, 0.05])
    up /= np.linalg.norm(up)
    R = calib.frame_from_up(up)
    np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.linalg.norm(R[0]) == pytest.approx(1.0)


def test_device_cal_tilt_zero_when_flat():
    dev = _flat_device("0001-1", angle_deg=0.0)
    assert dev.tilt_deg == pytest.approx(0.0, abs=1e-6)
    np.testing.assert_allclose(dev.up, [0.0, 0.0, 1.0], atol=1e-9)


def test_device_cal_tilt_from_tilted_gravity():
    n = 400
    gal = np.zeros((n, 3))
    gal[:, 0] = 100.0   # x方向にも重力成分。傾いた状態を模す
    gal[:, 2] = G
    dev = calib.DeviceCal("0001-1", 1, onset_us=int(3.0 * 1e6), gal=gal, start_us=0, fs=FS)
    expected_tilt = np.degrees(np.arctan2(100.0, G))
    assert dev.tilt_deg == pytest.approx(expected_tilt, abs=0.1)


def test_fit_relative_azimuth_recovers_known_rotation():
    ref = _flat_device("0001-1", angle_deg=0.0)
    for true_angle in (25.0, -40.0, 170.0):
        other = _flat_device("0002-1", angle_deg=true_angle)
        theta, coherence, lag_ms = calib.fit_relative_azimuth(ref, other)
        assert coherence > 0.99
        # 主軸は符号不定(±180度)になりうるタップ方向なので、mod180で比較する。
        assert abs(((theta - true_angle) + 90) % 180 - 90) < 1.0
        assert lag_ms == 0


def test_fit_relative_azimuth_recovers_lag():
    ref = _flat_device("0001-1", angle_deg=0.0)
    other = _flat_device("0002-1", angle_deg=10.0, lag_samples=3)  # 30ms先行
    theta, coherence, lag_ms = calib.fit_relative_azimuth(ref, other)
    assert coherence > 0.99
    assert lag_ms == pytest.approx(-30, abs=1)


def test_device_of_rejects_bad_format():
    with pytest.raises(SystemExit):
        calib.device_of("not-an-eid")
