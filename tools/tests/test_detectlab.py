import numpy as np
import pytest

import detectlab
from gen_synthetic import synth_noise, synth_quake

FS = 100.0
SECS = 120.0
BURST_OFF_S = 60.0        # ノイズ窓のどこに地震を差し込むか
BURST_LEN_S = 12.0        # 地震バーストの長さ
BURST_PEAK_S = BURST_OFF_S + BURST_LEN_S * 0.35  # synth_quake の包絡ピーク位置


def _stalta(data):
    band = detectlab.bandpass(data, FS, 1.0, 10.0)
    cf = (band ** 2).sum(axis=1)
    return detectlab.sta_lta(cf, FS, 1.0, 20.0)


def _buried_quake(amp_gal):
    """長い静置ノイズの途中に短い地震バーストを差し込んだ波形を返す。"""
    data = synth_noise(FS, SECS, rms_gal=0.2, seed=7)
    burst = synth_quake(FS, BURST_LEN_S, amp_gal=amp_gal, center_hz=3.0, seed=3)
    off = int(BURST_OFF_S * FS)
    data[off:off + len(burst)] += burst
    return data


def test_stalta_fires_on_buried_quake():
    # 静置ノイズに埋めた短い地震。帯域集中した過渡は STA/LTA で明確に立ち上がる。
    ratio = _stalta(_buried_quake(amp_gal=5.0))
    nratio = _stalta(synth_noise(FS, SECS, rms_gal=0.2, seed=7))

    # 過渡がノイズ由来のふらつきより十分大きく立つ
    assert ratio.max() > 3 * nratio.max()
    # ピークは差し込んだ包絡ピーク付近
    peak_t = ratio.argmax() / FS
    assert abs(peak_t - BURST_PEAK_S) < 6.0

    onsets = detectlab.detect_onsets(ratio, FS, start_us=0, thr=6.0)
    assert onsets, "地震があるのに onset を拾えていない"
    first_t = onsets[0] / 1e6
    assert BURST_OFF_S - 2.0 < first_t < BURST_PEAK_S + 3.0


def test_no_false_onset_on_pure_noise():
    noise = synth_noise(FS, SECS, rms_gal=0.3, seed=11)
    ratio = _stalta(noise)
    onsets = detectlab.detect_onsets(ratio, FS, start_us=0, thr=6.0)
    assert onsets == []


def test_bandpass_rejects_out_of_band():
    n = 6000
    t = np.arange(n) / FS
    inband = 0.5 * np.sin(2 * np.pi * 3.0 * t)          # 帯域内
    mixed = np.sin(2 * np.pi * 0.2 * t) + inband        # 0.2Hzは帯域外
    band = detectlab.bandpass(np.stack([mixed] * 3, axis=1), FS, 1.0, 10.0)
    ref = detectlab.bandpass(np.stack([inband] * 3, axis=1), FS, 1.0, 10.0)
    # 端の過渡を避けて中央で比較。帯域外(0.2Hz)が落ちて帯域内3Hzだけ残る。
    s = slice(1000, 5000)
    np.testing.assert_allclose(band[s], ref[s], atol=0.05)


def test_dump_csv_roundtrip(tmp_path):
    data = synth_quake(FS, 5.0, amp_gal=3.0, seed=1)
    path = tmp_path / "w.csv"
    detectlab.dump_csv(str(path), data, start_us=1000, fs=FS)

    back, start_us, fs = detectlab.load_csv(str(path))
    assert start_us == 1000
    assert fs == pytest.approx(FS, rel=1e-3)
    assert back.shape == data.shape
    np.testing.assert_allclose(back, data, atol=1e-4)


def test_at_to_us_jst():
    us = detectlab.at_to_us("2026-07-24 20:53")
    # JSTの20:53 = UTC 11:53
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(us / 1e6, timezone.utc)
    assert (dt.hour, dt.minute) == (11, 53)
