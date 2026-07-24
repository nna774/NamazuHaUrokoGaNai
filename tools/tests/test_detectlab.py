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


def test_rectilinearity_linear_vs_isotropic():
    # 直線偏光(1軸に沿った運動)は直線性が高く、等方ランダムは低い。
    n = 4000
    t = np.arange(n) / FS
    s = np.sin(2 * np.pi * 3.0 * t)
    linear = np.stack([s, 0.5 * s, 0.2 * s], axis=1)  # 全軸が同位相=直線
    rng = np.random.default_rng(0)
    iso = rng.standard_normal((n, 3))                  # 等方ノイズ
    rl = detectlab.rectilinearity(linear, FS, 2.0)
    ri = detectlab.rectilinearity(iso, FS, 2.0)
    s2 = slice(500, 3500)  # 端の移動窓の欠けを避ける
    assert rl[s2].mean() > 0.9
    assert ri[s2].mean() < 0.5
    assert rl[s2].mean() > ri[s2].mean() + 0.3


def test_rectilinearity_lifts_on_buried_quake():
    # 埋めた地震(帯域集中の実体波的過渡)は、その区間で直線性が背景より上がる。
    data = _buried_quake(amp_gal=5.0)
    rect = detectlab.rectilinearity(detectlab.bandpass(data, FS, 1.0, 10.0), FS, 3.0)
    i0 = int((BURST_OFF_S + 1) * FS)
    i1 = int((BURST_OFF_S + BURST_LEN_S - 1) * FS)
    quake_rect = rect[i0:i1].mean()
    noise_rect = rect[int(10 * FS):int(50 * FS)].mean()  # 地震前のノイズ区間
    assert quake_rect > noise_rect


def test_hypocentral_and_arrival_order():
    # 福島県沖 → 湯沢。震源距離は数百km、S波はP波より遅い。
    hypo, epi = detectlab.hypocentral_km(37.7, 141.7, 60.0, *detectlab.DEFAULT_STATION)
    assert 200 < epi < 320
    assert hypo > epi  # 深さぶん震源距離のほうが長い
    origin = detectlab.at_to_us("2026-07-24 20:52:59")
    p0, p1 = detectlab.arrival_window(hypo, origin, detectlab.P_VEL_RANGE)
    s0, s1 = detectlab.arrival_window(hypo, origin, detectlab.S_VEL_RANGE)
    assert p0 < p1 < s0 < s1  # P窓はS窓より前
    assert p0 > origin        # 発生より後に到達


def test_parse_eew_roundtrip():
    lat, lon, depth, origin = detectlab.parse_eew("37.7,141.7,60,2026-07-24 20:52:59")
    assert (lat, lon, depth) == (37.7, 141.7, 60.0)
    assert origin == detectlab.at_to_us("2026-07-24 20:52:59")
    with pytest.raises(SystemExit):
        detectlab.parse_eew("37.7,141.7,60")  # 発生時刻が欠けている
