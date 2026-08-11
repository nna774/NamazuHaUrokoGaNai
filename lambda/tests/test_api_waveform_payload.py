import os

import numpy as np

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from api import handler as api  # noqa: E402


def test_pad_to_3ch_leaves_3axis_untouched():
    gal = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    out = api._pad_to_3ch(gal)
    np.testing.assert_array_equal(out, gal)


def test_pad_to_3ch_pads_1axis_with_zeros():
    """axes=1の非校正センサ(ピエゾ等)は、y,z列を0埋めして3列に揃える。"""
    gal = np.array([[1.0], [2.0], [3.0]])
    out = api._pad_to_3ch(gal)
    assert out.shape == (3, 3)
    np.testing.assert_array_equal(out[:, 0], [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(out[:, 1], [0.0, 0.0, 0.0])
    np.testing.assert_array_equal(out[:, 2], [0.0, 0.0, 0.0])


def test_waveform_payload_raw_mode_pads_1axis():
    gal = np.array([[1.0], [2.0]])
    payload = api._waveform_payload(gal, start_us=0, fs=100.0)
    assert payload["mode"] == "raw"
    assert payload["x"] == [1.0, 2.0]
    assert payload["y"] == [0.0, 0.0]
    assert payload["z"] == [0.0, 0.0]


def test_waveform_payload_envelope_mode_pads_1axis():
    n = api.MAX_POINTS + 10
    gal = np.arange(n, dtype=float).reshape(-1, 1)
    payload = api._waveform_payload(gal, start_us=0, fs=100.0)
    assert payload["mode"] == "envelope"
    assert all(v == 0.0 for v in payload["y_min"])
    assert all(v == 0.0 for v in payload["y_max"])
    assert all(v == 0.0 for v in payload["z_min"])
    assert all(v == 0.0 for v in payload["z_max"])
