"""raw/ の窓組み立て。多点運用でデバイスを混ぜないことを固定する。

2台目を足した瞬間に、1号機の窓に2号機の波形が連結されて震度5が出た。
キーは raw/.../<device>-<startus>.bin なので、時別prefixで列挙して sort() すると
**デバイス番号が先に効く**。時系列に見えて「1号機の全部→2号機の全部」の順になる。
"""

import numpy as np
import pytest

from common import s3util, store, wire


class FakeS3:
    """list_objects_v2 / get_object だけの最小スタブ。Prefix 絞り込みを再現する。"""

    def __init__(self, objects):
        self.objects = objects  # {key: bytes}
        self.listed_prefixes = []
        self.get_keys = []

    def list_objects_v2(self, **kw):
        prefix = kw["Prefix"]
        self.listed_prefixes.append(prefix)
        keys = sorted(k for k in self.objects if k.startswith(prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket, Key):  # noqa: N803
        self.get_keys.append(Key)
        return {"Body": _Body(self.objects[Key])}


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


def test_load_window_skips_get_for_batches_outside_window(s3):
    """list_raw_keys_in_range は時間帯(hour)+deviceまでしか絞れないので、
    同じ時間帯の遠いバッチもキーとして渡ってくる。GETする前にファイル名の
    startusだけで弾けているか（全部GETしてから捨てていないか）を確認する。
    起きた不具合: 窓を絞ってもGET数がその時間帯の総バッチ数のままで、
    /recent が分数によらず一定時間（数秒）かかっていた。
    """
    far_st = T0 + 3_000_000_000  # 同じ時間帯(hour)だが50分後。窓には絶対入らない。
    s3.objects[s3util.raw_key(1, far_st)] = build(1, far_st, dc_gal=-7.0)
    store.load_window(s3, "b", T0 + 4_000_000, 10.0, device_id=1)
    assert all(not k.endswith(f"{far_st:020d}.bin") for k in s3.get_keys)


def test_copy_raw_to_event_only_copies_one_device(s3):
    copied = []
    s3.copy_object = lambda **kw: copied.append(kw["CopySource"]["Key"])
    n = store.copy_raw_to_event(s3, "b", "0002-1", T0, T0 + 4_000_000, device_id=2)
    assert n == 4
    assert all("/0002-" in k for k in copied)


def test_load_window_keeps_only_the_trailing_segment_across_a_real_gap():
    """バッチ間に許容ジッタを超える空き(WiFi再接続等)があったら、`load_window`は
    末尾（＝直近）の連続区間だけを返す（2026-08-29 NERV防災通知の事後解析で発見）。

    単純に全部連結すると、欠落後のサンプルの時刻が win_start + i/fs で実時刻より
    欠落秒数ぶん早く計算され、onset時刻が実際より早くズレる。
    """
    objs = {}
    # 欠落前: dc_gal=-7.0 のバッチが2本(T0, T0+1_000_000)
    for i in range(2):
        st = T0 + i * 1_000_000
        objs[s3util.raw_key(1, st)] = build(1, st, dc_gal=-7.0)
    # 40秒の欠落(BATCH_GAP_TOLERANCE_USを大きく超える)を挟んで、欠落後: dc_gal=+42.0
    gap_start = T0 + 2_000_000 + 40_000_000
    for i in range(2):
        st = gap_start + i * 1_000_000
        objs[s3util.raw_key(1, st)] = build(1, st, dc_gal=+42.0)
    s3 = FakeS3(objs)

    gal, win_start, _ = store.load_window(
        s3, "b", gap_start + 2_000_000, seconds=200.0, device_id=1)

    assert win_start == gap_start
    assert gal.shape[0] == 200  # 欠落前の2バッチ(200サンプル)は含まれない
    assert gal[:, 0].max() - gal[:, 0].min() == pytest.approx(0.0, abs=1e-6)


def _events_with_two_gaps():
    """先頭区間(dc=-1)・欠落・onsetを含む中央区間(dc=+99)・欠落・post側区間(dc=-3)
    の3区間を持つイベントを作る。2026-08-29の群馬県北部M3.2の事後解析で実際に
    踏んだ形（保存範囲に2回の無関係な欠落があり、onsetは先頭でも末尾でもない
    真ん中の区間に入っていた）そのもの。"""
    objs = {}
    for i in range(2):
        st = T0 + i * 1_000_000
        objs[s3util.event_batch_key("0002-x", st)] = build(2, st, dc_gal=-1.0)
    mid_start = T0 + 2_000_000 + 40_000_000
    onset_us = mid_start + 500_000  # 中央区間の内側
    for i in range(2):
        st = mid_start + i * 1_000_000
        objs[s3util.event_batch_key("0002-x", st)] = build(2, st, dc_gal=+99.0)
    post_start = mid_start + 2_000_000 + 40_000_000
    for i in range(2):
        st = post_start + i * 1_000_000
        objs[s3util.event_batch_key("0002-x", st)] = build(2, st, dc_gal=-3.0)
    return FakeS3(objs), mid_start, onset_us


def test_load_event_picks_the_segment_containing_near_us():
    """`near_us`(通常はonset_us)を渡したら、それを含む区間を返す——先頭でも
    末尾でもない真ん中の区間に入っていても正しく拾える。"""
    s3, mid_start, onset_us = _events_with_two_gaps()

    gal, win_start, _ = store.load_event(s3, "b", "0002-x", near_us=onset_us)

    assert win_start == mid_start
    assert gal.shape[0] == 200
    assert gal[:, 0].max() - gal[:, 0].min() == pytest.approx(0.0, abs=1e-6)
    assert gal[0, 0] > 50  # dc_gal=+99.0側の区間が返っている


def test_load_event_without_near_us_falls_back_to_the_largest_segment():
    """`near_us`未指定なら最大（サンプル数最多）の区間を返す。"""
    objs = {}
    for i in range(2):  # 小さい先頭区間(200サンプル)
        st = T0 + i * 1_000_000
        objs[s3util.event_batch_key("0002-y", st)] = build(2, st, dc_gal=-1.0, n=100)
    big_start = T0 + 2_000_000 + 40_000_000
    for i in range(5):  # 大きい後続区間(500サンプル)
        st = big_start + i * 1_000_000
        objs[s3util.event_batch_key("0002-y", st)] = build(2, st, dc_gal=+42.0, n=100)
    s3 = FakeS3(objs)

    gal, win_start, _ = store.load_event(s3, "b", "0002-y")

    assert win_start == big_start
    assert gal.shape[0] == 500
