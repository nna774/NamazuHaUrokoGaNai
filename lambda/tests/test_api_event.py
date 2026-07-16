import os

import numpy as np

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from api import handler as api  # noqa: E402

FS = 100.0
START = 1_000_000_000_000  # 適当な基準時刻 [us]


def _gal(n):
    """値=サンプル番号 の波形。切り出し位置の検証に使う。"""
    v = np.arange(n, dtype=float)
    return np.stack([v, v, v], axis=1)


def test_slice_gal_middle():
    # 12000サンプル(120秒)から中央の10秒を切り出す
    gal, start = api._slice_gal(_gal(12000), START, FS,
                                str(START + int(55e6)), str(START + int(65e6)))
    assert start == START + int(55e6)
    assert gal[0, 0] == 5500
    # ceil(+1) で終端を含むぶん 1002 点になる（10秒×100Hz + 両端）
    assert 1000 <= gal.shape[0] <= 1002
    assert gal.shape[0] <= api.MAX_POINTS  # raw で返せる幅


def test_slice_gal_clamps_out_of_range():
    # 窓の外にはみ出す指定は端にクランプされる
    gal, start = api._slice_gal(_gal(1000), START, FS,
                                str(START - int(5e6)), str(START + int(2e6)))
    assert start == START
    assert gal[0, 0] == 0
    assert gal.shape[0] == 201  # [0, 2s] のみ


def test_slice_gal_ignores_bad_or_empty():
    g = _gal(1000)
    # パース不能・逆転・未指定は全体をそのまま返す
    for frm, to in [("x", "y"), (str(START + int(5e6)), str(START + int(1e6))), (None, None)]:
        gal, start = api._slice_gal(g, START, FS, frm, to)
        assert gal.shape[0] == 1000 and start == START
    # 完全に範囲外（実質空）も全体を返す
    gal, start = api._slice_gal(g, START, FS,
                                str(START + int(100e6)), str(START + int(110e6)))
    assert gal.shape[0] == 1000 and start == START


def test_slice_gal_empty_waveform():
    gal, start = api._slice_gal(np.empty((0, 3)), START, FS, "1", "2")
    assert gal.shape[0] == 0 and start == START
