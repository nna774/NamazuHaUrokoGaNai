import struct

import numpy as np
import pytest

from common import wire


def build_batch(device_id=1, start_us=1_720_000_000_000_000, fs=100, scale=0.076,
                samples=None):
    """firmware WireFormat.h と同じバイト列を作る。"""
    if samples is None:
        samples = np.array([[1, -2, 3], [100, 200, -300]], dtype=np.int16)
    count = samples.shape[0]
    header = struct.pack(
        wire.HEADER_FMT,
        wire.MAGIC, 1, 0, 0, 3, start_us, fs * 1000, count, scale, device_id)
    return header + samples.astype("<i2").tobytes()


def test_roundtrip_header_and_samples():
    samples = np.array([[1, -2, 3], [100, 200, -300], [0, 0, 32767]], dtype=np.int16)
    data = build_batch(samples=samples)
    b = wire.parse(data)
    assert b.meta.device_id == 1
    assert b.meta.sample_count == 3
    assert b.meta.sample_rate_hz == 100.0
    assert b.meta.scale_mg_per_lsb == pytest.approx(0.076, rel=1e-5)
    np.testing.assert_array_equal(b.raw, samples.astype(np.int64))


def test_gal_conversion():
    samples = np.array([[1000, 0, 0]], dtype=np.int16)
    b = wire.parse(build_batch(scale=0.076, samples=samples))
    # 1000 LSB * 0.076 mg/LSB * 0.980665 gal/mg
    assert b.gal[0, 0] == pytest.approx(1000 * 0.076 * 0.980665, rel=1e-6)


def test_bad_magic_rejected():
    data = build_batch()
    bad = b"\x00\x00\x00\x00" + data[4:]
    with pytest.raises(ValueError):
        wire.parse(bad)


def test_timestamps():
    b = wire.parse(build_batch(start_us=1000, fs=100))
    ts = b.timestamps_us()
    assert ts[0] == 1000
    assert ts[1] == 1000 + 10000  # 10ms
