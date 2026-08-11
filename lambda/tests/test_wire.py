import struct

import numpy as np
import pytest

from common import wire


def build_batch(device_id=1, start_us=1_720_000_000_000_000, fs=100, scale=0.076,
                samples=None, version=1, sensor_type=0, sample_format=0, trailer=b"",
                axes=None):
    """firmware WireFormat.h と同じバイト列を作る。"""
    if samples is None:
        samples = np.array([[1, -2, 3], [100, 200, -300]], dtype=np.int16)
    if axes is None:
        axes = samples.shape[1]
    dtype = "<i4" if sample_format == 1 else "<i2"
    count = samples.shape[0]
    header = struct.pack(
        wire.HEADER_FMT,
        wire.MAGIC, version, sensor_type, sample_format, axes, start_us,
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


def test_adxl355_temp_intercept_is_not_the_adxl359_value():
    """1852 は ADXL359 の切片。取り違えると常時 3.6℃ ずれる。

    出典: Linux drivers/iio/accel/adxl355_core.c（ADXL355=1885 / ADXL359=1852）。
    ADI のデモコード(ADuCM360_demo_adxl355_pmdz)が 1852 を使っているので混同しやすい。
    """
    assert wire.ADXL355_TEMP_AT_25C == 1885.0


def test_iis3dhhc_temp_conversion():
    # raw=0 が基準点で25℃（データシート DS12292 §7.6: 16bit生値は12bit値が左詰め、
    # よって raw/256+25。下位4bitは常にパディング0なので raw=256刻みで1℃動く）。
    assert wire.iis3dhhc_temp_c(0) == pytest.approx(25.0)
    assert wire.iis3dhhc_temp_c(256) == pytest.approx(26.0)
    # raw は符号付き16bitのビット列をuint16のまま運ぶ。負値（0x8000超）も符号拡張して扱う。
    assert wire.iis3dhhc_temp_c(0x10000 - 256) == pytest.approx(24.0)


def test_temp_c_for_adxl355_and_iis3dhhc():
    assert wire.temp_c_for(wire.SENSOR_TYPE_ADXL355, 1900) == pytest.approx(wire.adxl355_temp_c(1900))
    assert wire.temp_c_for(wire.SENSOR_TYPE_IIS3DHHC, 1900) == pytest.approx(wire.iis3dhhc_temp_c(1900))
    assert wire.temp_c_for(wire.SENSOR_TYPE_ADXL355, None) is None


def test_temp_c_for_adxl355_and_iis3dhhc_via_meta():
    meta_adxl = wire.parse(build_batch(
        version=2, sensor_type=wire.SENSOR_TYPE_ADXL355,
        trailer=tlv(wire.TRAILER_SENSOR_TEMP, struct.pack("<H", 1900)))).meta
    assert wire.temp_c(meta_adxl) == pytest.approx(wire.adxl355_temp_c(1900))

    meta_iis = wire.parse(build_batch(
        version=2, sensor_type=wire.SENSOR_TYPE_IIS3DHHC,
        trailer=tlv(wire.TRAILER_SENSOR_TEMP, struct.pack("<H", 1900)))).meta
    assert wire.temp_c(meta_iis) == pytest.approx(wire.iis3dhhc_temp_c(1900))


def test_temp_c_none_without_trailer():
    meta = wire.parse(build_batch(version=2, sensor_type=wire.SENSOR_TYPE_ADXL355)).meta
    assert wire.temp_c(meta) is None


def test_axes_1_piezo_like_sensor():
    """非校正の1軸センサ(ピエゾ等)はaxes=1で送る想定（docs/wire_format.md）。"""
    samples = np.array([[10], [-20], [30]], dtype=np.int16)
    b = wire.parse(build_batch(sensor_type=wire.SENSOR_TYPE_PIEZO, samples=samples))
    assert b.meta.axes == 1
    assert b.raw.shape == (3, 1)
    assert b.gal.shape == (3, 1)
    np.testing.assert_array_equal(b.raw, samples.astype(np.int64))


def test_axes_0_rejected():
    data = build_batch(axes=0)
    with pytest.raises(ValueError):
        wire.parse(data)


def test_is_calibrated_accel_sensors():
    assert wire.is_calibrated(wire.SENSOR_TYPE_IIS3DHHC)
    assert wire.is_calibrated(wire.SENSOR_TYPE_ADXL355)
    assert wire.is_calibrated(127)  # 加速度センサ帯の上限


def test_is_calibrated_piezo_and_reserved_are_not():
    assert not wire.is_calibrated(wire.SENSOR_TYPE_PIEZO)
    assert not wire.is_calibrated(249)  # 非校正センサ帯の上限
    assert not wire.is_calibrated(250)  # 予約域


def test_is_calibrated_fake_is_treated_as_calibrated():
    """FAKEは結合試験用にgal相当の値を実際に送るため、非校正扱いにしない。"""
    assert wire.is_calibrated(wire.SENSOR_TYPE_FAKE)
