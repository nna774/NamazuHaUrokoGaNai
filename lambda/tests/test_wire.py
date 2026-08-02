import struct

import numpy as np
import pytest

from common import wire


def build_batch(device_id=1, start_us=1_720_000_000_000_000, fs=100, scale=0.076,
                samples=None, version=1, sensor_type=0, sample_format=0, trailer=b""):
    """firmware WireFormat.h と同じバイト列を作る。"""
    if samples is None:
        samples = np.array([[1, -2, 3], [100, 200, -300]], dtype=np.int16)
    dtype = "<i4" if sample_format == 1 else "<i2"
    count = samples.shape[0]
    header = struct.pack(
        wire.HEADER_FMT,
        wire.MAGIC, version, sensor_type, sample_format, 3, start_us,
        fs * 1000, count, scale, device_id)
    return header + samples.astype(dtype).tobytes() + trailer


def tlv(typ, payload):
    return struct.pack(wire.TLV_HEADER_FMT, typ, len(payload)) + payload


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


def test_v1_without_trailer():
    b = wire.parse(build_batch())
    assert b.meta.trailer == {}
    assert b.meta.sensor_temp_raw is None


def test_v2_temperature_trailer():
    data = build_batch(version=2, sensor_type=1, sample_format=1,
                       samples=np.array([[1, 2, 3]], dtype=np.int32),
                       trailer=tlv(wire.TRAILER_SENSOR_TEMP, struct.pack("<H", 1900)))
    b = wire.parse(data)
    assert b.meta.version == 2
    assert b.meta.sensor_temp_raw == 1900
    np.testing.assert_array_equal(b.raw, np.array([[1, 2, 3]], dtype=np.int64))


def test_unknown_trailer_type_is_kept_and_skipped():
    """知らない type が来ても len ぶん読み飛ばして次を読めること（TLVの要点）。"""
    data = build_batch(version=2,
                       trailer=tlv(999, b"\xde\xad\xbe\xef")
                       + tlv(wire.TRAILER_SENSOR_TEMP, struct.pack("<H", 1852)))
    b = wire.parse(data)
    assert b.meta.trailer[999] == b"\xde\xad\xbe\xef"
    assert b.meta.sensor_temp_raw == 1852


def test_truncated_trailer_does_not_break_samples():
    """トレイラーが壊れていても波形は捨てない（補助情報にすぎないため）。"""
    samples = np.array([[7, 8, 9]], dtype=np.int16)
    data = build_batch(version=2, samples=samples,
                       trailer=struct.pack(wire.TLV_HEADER_FMT, 1, 8) + b"\x01")
    b = wire.parse(data)
    np.testing.assert_array_equal(b.raw, samples.astype(np.int64))
    assert b.meta.sensor_temp_raw is None


def test_adxl355_temp_conversion_is_relative():
    # 公称の基準点で25℃。絶対精度は無いが、傾きの符号と大きさは固定しておく。
    assert wire.adxl355_temp_c(wire.ADXL355_TEMP_AT_25C) == pytest.approx(25.0)
    # LSBが増える向きは温度が下がる向き（傾きが負）
    assert wire.adxl355_temp_c(wire.ADXL355_TEMP_AT_25C + 9.05) == pytest.approx(24.0)
