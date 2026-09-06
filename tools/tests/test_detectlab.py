import sys

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


def test_rectilinearity_two_axis():
    # 2軸(水平のみ)でも動く。直線運動は高く、等方は低い。
    n = 4000
    t = np.arange(n) / FS
    s = np.sin(2 * np.pi * 3.0 * t)
    linear = np.stack([s, 0.4 * s], axis=1)          # 2軸で直線
    rng = np.random.default_rng(1)
    iso = rng.standard_normal((n, 2))
    s2 = slice(500, 3500)
    assert detectlab.rectilinearity(linear, FS, 2.0)[s2].mean() > 0.9
    assert detectlab.rectilinearity(iso, FS, 2.0)[s2].mean() < 0.5


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


def test_rolling_correlation_high_when_signals_share_source():
    # 同じ元信号+独立ノイズの2系列は高相関、独立ノイズ同士は低相関に留まる。
    n = 3000
    t = np.arange(n) / FS
    rng = np.random.default_rng(2)
    common = np.sin(2 * np.pi * 0.5 * t)
    a = common + 0.05 * rng.standard_normal(n)
    b = common + 0.05 * rng.standard_normal(n)
    noise_a = rng.standard_normal(n)
    noise_b = rng.standard_normal(n)
    corr_shared = detectlab.rolling_correlation(a, b, FS, win_s=2.0)
    corr_indep = detectlab.rolling_correlation(noise_a, noise_b, FS, win_s=2.0)
    assert np.nanmean(corr_shared) > 0.9
    assert abs(np.nanmean(corr_indep)) < 0.3


def test_rolling_correlation_leading_nan_until_window_fills():
    a = np.arange(100.0)
    corr = detectlab.rolling_correlation(a, a, FS, win_s=0.5)  # win=50 samples
    assert np.all(np.isnan(corr[:50]))
    assert np.isfinite(corr[50:]).all()


def test_align_pair_interpolates_onto_overlap_only():
    # b は a よりわずかに遅れて始まり早く終わる → 重なりはその内側だけ。
    fs = 10.0
    t_a = np.arange(0, 5, 1 / fs)
    y_a = np.sin(t_a)
    t_b = np.arange(1, 4, 1 / fs) + 0.03  # サンプル境界がズレている
    y_b = np.sin(t_b)
    t_c, ya, yb = detectlab.align_pair(t_a, y_a, t_b, y_b, fs)
    assert t_c[0] >= t_b[0] and t_c[-1] <= t_b[-1]
    assert t_c[0] >= t_a[0] and t_c[-1] <= t_a[-1]
    # 補間後は同じsin波形同士なのでほぼ一致するはず
    assert np.allclose(ya, yb, atol=0.01)


def test_align_pair_empty_when_no_overlap():
    fs = 10.0
    t_a = np.arange(0, 1, 1 / fs)
    t_b = np.arange(10, 11, 1 / fs)
    t_c, ya, yb = detectlab.align_pair(t_a, np.zeros_like(t_a), t_b, np.zeros_like(t_b), fs)
    assert len(t_c) == 0


def test_pair_rolling_correlation_matches_manual_calc():
    # per_deviceタプル(device_id, start_us, fs, ratio, rect, onsets)からの計算が、
    # align_pair+rolling_correlationを手で呼んだ場合と一致することを確認する。
    fs = 10.0
    n = 200
    rng = np.random.default_rng(3)
    common = np.sin(2 * np.pi * 0.3 * np.arange(n) / fs)
    rect_a = common + 0.02 * rng.standard_normal(n)
    rect_b = common + 0.02 * rng.standard_normal(n)
    per_device = [
        (1, 0, fs, None, rect_a, []),
        (2, 0, fs, None, rect_b, []),
    ]
    t_c, corr = detectlab.pair_rolling_correlation(per_device, ref_us=0, corr_win=2.0)
    t = np.arange(n) / fs
    expected_t, ea, eb = detectlab.align_pair(t, rect_a, t, rect_b, fs)
    expected_corr = detectlab.rolling_correlation(ea, eb, fs, 2.0)
    assert np.allclose(t_c, expected_t)
    np.testing.assert_allclose(corr, expected_corr, equal_nan=True)


def test_print_corr_bin_report_flags_elevated_window(capsys):
    fs = 10.0
    n = 400
    t = np.arange(n) / fs
    corr = np.full(n, -0.1)
    corr[(t >= 20) & (t < 40)] = 0.9  # 立ち上がり区間
    detectlab.print_corr_bin_report(t, corr, bin_s=20.0, thr=0.6, origin_us=None)
    out = capsys.readouterr().out
    assert "t=[    20,    40)s" in out
    assert "frac(corr>=0.6)=1.00" in out


def test_print_corr_bin_report_prints_background_when_origin_given(capsys):
    t = np.linspace(-160, -20, 100)
    corr = np.full_like(t, 0.8)
    detectlab.print_corr_bin_report(t, corr, bin_s=20.0, thr=0.6, origin_us=0)
    out = capsys.readouterr().out
    assert "背景(t=-150〜-30s)" in out


def test_print_corr_bin_report_handles_empty_input(capsys):
    detectlab.print_corr_bin_report(np.array([]), np.array([]), bin_s=20.0, thr=0.6, origin_us=None)
    out = capsys.readouterr().out
    assert "データなし" in out


def test_coda_window_starts_at_s_window_end_and_spans_coda_s():
    # S窓終了から後ろCODA_S秒ぶんが「コーダ想定域」——ピーク振幅が到達"瞬間"の窓の外に
    # 来ることがあるため(2026-08-26福島県沖M4.5の事後解析で自動化した)。
    origin_us = 0
    s_win = detectlab.arrival_window(200.0, origin_us, detectlab.S_VEL_RANGE)
    coda_win = (s_win[1], s_win[1] + int(detectlab.CODA_S * 1e6))
    assert coda_win[0] == s_win[1]
    assert (coda_win[1] - coda_win[0]) / 1e6 == detectlab.CODA_S
    assert detectlab.CODA_S > 0


def test_classify_snr_wrect_thresholds():
    # 重ね描き時の窓別レポート表(パターンB)とreport()の標準出力が同じ分類を共有する。
    assert detectlab.classify_snr_wrect(snr=2.0, wrect=0.7) == "地震らしい"
    assert detectlab.classify_snr_wrect(snr=1.5, wrect=0.6) == "地震らしい"
    assert detectlab.classify_snr_wrect(snr=1.0, wrect=0.9) == "微妙"
    assert detectlab.classify_snr_wrect(snr=1.4, wrect=0.4) == "要検討"


def test_expand_event_ids_builds_full_ids_from_bare_suffix():
    # "59577127"のような裸のバケット番号は --device と組んで完全なIDへ展開される
    assert detectlab.expand_event_ids(["59577127"], [1, 2]) == \
        ["0001-59577127", "0002-59577127"]


def test_expand_event_ids_passes_full_ids_through():
    # "-"を含む値(すでに完全なevent_id)はそのまま通す
    ids = ["0001-59577127", "0002-59577127"]
    assert detectlab.expand_event_ids(ids, [1]) == ids


def test_expand_event_ids_mixes_bare_and_full():
    out = detectlab.expand_event_ids(["0003-59573459", "59577127"], [1, 2])
    assert out == ["0003-59573459", "0001-59577127", "0002-59577127"]


def test_main_at_single_device_without_event(monkeypatch, tmp_path):
    # --event無し(--at系)でargs.eventがNoneのまま`len(args.event)`に渡ると落ちる回帰
    # （b97892bで`elif args.event:`が`elif len(args.event) == 1:`に変わった際に混入）。
    data = synth_noise(FS, SECS, rms_gal=0.2, seed=1)
    monkeypatch.setattr(detectlab, "resolve_bucket", lambda explicit: "dummy-bucket")
    monkeypatch.setattr(detectlab, "load_s3_window",
                         lambda bucket, end_us, seconds, dev, use_cache=True: (data, 0, FS))
    out = tmp_path / "out.png"
    monkeypatch.setattr(sys, "argv", [
        "detectlab.py", "--at", "2026-07-24 20:53", "--device", "1",
        "--minutes", "1", "--lead-min", "1", "--out", str(out),
    ])
    assert detectlab.main() == 0
    assert out.exists()
