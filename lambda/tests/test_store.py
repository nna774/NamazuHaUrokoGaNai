"""raw/ の窓組み立て。多点運用でデバイスを混ぜないことを固定する。

2台目を足した瞬間に、1号機の窓に2号機の波形が連結されて震度5が出た。
キーは raw/.../<device>-<startus>.bin なので、時別prefixで列挙して sort() すると
**デバイス番号が先に効く**。時系列に見えて「1号機の全部→2号機の全部」の順になる。
"""

import numpy as np
import pytest

from batch_uplink import s3util

from common import store, wire


class FakeS3:
    """list_objects_v2 / get_object だけの最小スタブ。Prefix 絞り込みを再現する。"""

    def __init__(self, objects):
        self.objects = objects  # {key: bytes}
        self.listed_prefixes = []

    def list_objects_v2(self, **kw):
        prefix = kw["Prefix"]
        self.listed_prefixes.append(prefix)
        keys = sorted(k for k in self.objects if k.startswith(prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket, Key, Range=None):  # noqa: N803
        data = self.objects[Key]
        if Range is not None:
            # "bytes=X-Y" / "bytes=X-"（末尾まで）だけ対応。実S3同様、末尾より先を
            # 指すと416相当（load_temp_series の v1バッチ握りつぶしを再現するため）。
            spec = Range.removeprefix("bytes=")
            lo_s, _, hi_s = spec.partition("-")
            lo = int(lo_s)
            if lo >= len(data):
                raise ValueError(f"InvalidRange: {Range} for {len(data)} bytes")
            hi = int(hi_s) if hi_s else len(data) - 1
            data = data[lo:hi + 1]
        return {"Body": _Body(data)}


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


def build(device_id, start_us, dc_gal, n=100):
    """dc_gal を x に乗せた n サンプルのバッチ。scale=1mg/LSB で作る。"""
    import struct
    scale = 1.0
    lsb = int(round(dc_gal / (scale * wire.MG_TO_GAL)))
    samples = np.tile(np.array([[lsb, 0, 0]], dtype="<i2"), (n, 1))
    header = struct.pack(wire.HEADER_FMT, wire.MAGIC, 1, 0, 0, 3,
                         start_us, 100 * 1000, n, scale, device_id)
    return header + samples.tobytes()


T0 = 1_785_600_000_000_000  # 適当なUNIX時刻[us]


@pytest.fixture
def s3():
    objs = {}
    for i in range(4):  # 同じ時間帯に2デバイスぶん置く
        st = T0 + i * 1_000_000
        objs[s3util.raw_key(1, st)] = build(1, st, dc_gal=-7.0)
        objs[s3util.raw_key(2, st)] = build(2, st, dc_gal=+217.0)
    return FakeS3(objs)


def test_keys_sort_device_major_not_time_major(s3):
    """絞り込まないと「1号機の全部→2号機の全部」に並ぶ（バグの機序そのもの）。"""
    keys = store.list_raw_keys_in_range(s3, "b", T0, T0 + 4_000_000)
    devs = [k.rsplit("/", 1)[1].split("-")[0] for k in keys]
    assert devs == ["0001"] * 4 + ["0002"] * 4  # 時刻順ではない


def test_list_filters_by_device(s3):
    keys = store.list_raw_keys_in_range(s3, "b", T0, T0 + 4_000_000, device_id=2)
    assert len(keys) == 4
    assert all("/0002-" in k for k in keys)


def test_load_window_returns_single_device_only(s3):
    gal, _, _ = store.load_window(s3, "b", T0 + 4_000_000, 10.0, device_id=1)
    assert gal.shape[0] == 400
    # 1号機だけなら x は一定。混ざれば -7 と +217 の階段になる。
    assert gal[:, 0].max() - gal[:, 0].min() == pytest.approx(0.0, abs=1e-6)


def test_load_window_narrows_the_s3_prefix(s3):
    """デバイス絞り込みは S3 の Prefix に落ちること（列挙量も減る）。"""
    store.load_window(s3, "b", T0 + 4_000_000, 10.0, device_id=2)
    assert all(p.endswith("/0002-") for p in s3.listed_prefixes)


def test_copy_raw_to_event_only_copies_one_device(s3):
    copied = []
    s3.copy_object = lambda **kw: copied.append(kw["CopySource"]["Key"])
    n = store.copy_raw_to_event(s3, "b", "0002-1", T0, T0 + 4_000_000, device_id=2)
    assert n == 4
    assert all("/0002-" in k for k in copied)


def build_with_temp(device_id, start_us, temp_raw=None, sensor_type=1, n=10):
    """version2・温度トレイラー(任意)付きのバッチを組み立てる（load_temp_series用）。"""
    import struct
    scale = 1.0
    samples = np.zeros((n, 3), dtype="<i2")
    header = struct.pack(wire.HEADER_FMT, wire.MAGIC, 2, sensor_type, 0, 3,
                         start_us, 100 * 1000, n, scale, device_id)
    trailer = b""
    if temp_raw is not None:
        trailer = struct.pack(wire.TLV_HEADER_FMT, wire.TRAILER_SENSOR_TEMP, 2) \
            + struct.pack("<H", temp_raw)
    return header + samples.tobytes() + trailer


def test_load_temp_series_extracts_temp_without_full_payload():
    objs = {}
    for i in range(3):
        st = T0 + i * 15_000_000  # 15秒間隔
        objs[s3util.raw_key(2, st)] = build_with_temp(2, st, temp_raw=1900 + i)
    fake = FakeS3(objs)
    out = store.load_temp_series(fake, "b", T0 + 30_000_000, 60.0, device_id=2)
    assert [m.sensor_temp_raw for _, m in out] == [1900, 1901, 1902]
    assert [t for t, _ in out] == [T0, T0 + 15_000_000, T0 + 30_000_000]


def test_load_temp_series_skips_other_devices():
    objs = {
        s3util.raw_key(1, T0): build_with_temp(1, T0, temp_raw=1800),
        s3util.raw_key(2, T0): build_with_temp(2, T0, temp_raw=1900),
    }
    fake = FakeS3(objs)
    out = store.load_temp_series(fake, "b", T0 + 1_000_000, 60.0, device_id=2)
    assert len(out) == 1
    assert out[0][1].sensor_temp_raw == 1900


def test_load_temp_series_ignores_batches_without_trailer():
    """v1相当（トレイラー無し）は416相当を握りつぶして「温度なし」扱いにする。"""
    objs = {s3util.raw_key(2, T0): build_with_temp(2, T0, temp_raw=None)}
    fake = FakeS3(objs)
    out = store.load_temp_series(fake, "b", T0 + 1_000_000, 60.0, device_id=2)
    assert out == []


def test_load_temp_series_subsamples_to_max_points():
    objs = {}
    for i in range(20):
        st = T0 + i * 15_000_000
        objs[s3util.raw_key(2, st)] = build_with_temp(2, st, temp_raw=1900 + i)
    fake = FakeS3(objs)
    out = store.load_temp_series(fake, "b", T0 + 20 * 15_000_000, 3600.0,
                                 device_id=2, max_points=5)
    assert len(out) <= 5
    assert len(out) >= 1
