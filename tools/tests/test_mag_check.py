import numpy as np

import mag_check as mc


def _csv(xyz, status="0x00", dt_ms=20):
    lines = ["# begin status=0x00", "# t_ms,status,x_uT,y_uT,z_uT,temp_C"]
    for i, (x, y, z) in enumerate(xyz):
        lines.append(f"{i * dt_ms},{status},{x:.2f},{y:.2f},{z:.2f},25.0")
    return lines


def test_parse_skips_comments_bad_status_and_garbage():
    lines = _csv([(1, 2, 3)] * 3) + _csv([(9, 9, 9)], status="0x04")[2:] + ["garbage", "1,0x00,a,b,c,d"]
    d = mc.parse_csv(lines)
    assert d.shape == (3, 5)
    assert d[0, 1:4].tolist() == [1, 2, 3]


def test_sphere_fit_recovers_offset_and_radius():
    rng = np.random.default_rng(0)
    v = rng.normal(size=(2000, 3))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    c0 = np.array([-45.0, -35.0, -30.0])
    p = c0 + 48.0 * v + rng.normal(scale=0.3, size=v.shape)
    c, r, rms = mc.fit_sphere(p)
    assert np.allclose(c, c0, atol=0.5)
    assert abs(r - 48.0) < 0.5
    assert rms < 0.6


def test_analyze_flat_rotation_uses_circle_and_reports_offset():
    th = np.linspace(0, 4 * np.pi, 800)
    c0 = np.array([-40.0, 20.0])
    xyz = np.c_[c0[0] + 30 * np.cos(th), c0[1] + 30 * np.sin(th), np.full_like(th, -45.0)]
    res = mc.analyze(mc.parse_csv(_csv(xyz)))
    assert res["moving"] and res["fit"]["kind"] == "circle(XY)"
    assert np.allclose(res["fit"]["center"], c0, atol=0.2)
    assert abs(res["fit"]["radius"] - 30) < 0.2
    assert res["fit"]["coverage"] > 0.95
    assert "オフセット/半径" in mc.report(res)


def test_partial_arc_is_flagged():
    th = np.linspace(0, 1.0, 300)  # 約57度しか回していない
    xyz = np.c_[30 * np.cos(th), 30 * np.sin(th), np.full_like(th, -45.0)]
    res = mc.analyze(mc.parse_csv(_csv(xyz)))
    assert res["fit"]["note"] and "周回が足りない" in res["fit"]["note"]


def test_static_is_treated_as_drift_data_and_trend_is_per_hour():
    n = 600
    t_s = np.arange(n) * 1.0
    xyz = np.c_[-42 + 0.001 * t_s, np.full(n, -34.0), np.full(n, -86.0)]
    lines = [f"{int(t * 1000)},0x00,{x:.3f},{y:.3f},{z:.3f},25.0" for t, (x, y, z) in zip(t_s, xyz)]
    res = mc.analyze(mc.parse_csv(lines))
    assert not res["moving"]
    assert abs(res["drift_per_h"][0] - 3.6) < 0.1  # 0.001µT/s = 3.6µT/h
    assert "磁化" in mc.report(res)  # ノルム約100µTは地磁気の目安を大きく超える


def test_static_reports_temperature_coefficient():
    n = 600
    t_s = np.arange(n) * 1.0
    temp = 22.0 + 4.0 * t_s / t_s[-1]  # 22→26℃
    x = -42 + 0.5 * (temp - 22.0)  # 0.5µT/℃
    lines = [f"{int(t * 1000)},0x00,{xi:.3f},-34.000,-86.000,{ti:.2f}" for t, xi, ti in zip(t_s, x, temp)]
    res = mc.analyze(mc.parse_csv(lines))
    assert abs(res["temp_coef"][0] - 0.5) < 0.01
    assert abs(res["temp_coef"][1]) < 0.01
    assert "温度との回帰" in mc.report(res)


def test_longest_segment_drops_orphan_sample_before_gap():
    n = 200
    body = [f"{int(420000 + i * 260)},0x00,-2.85,30.00,-24.90,19.0" for i in range(n)]
    lines = ["0,0x00,-40.0,5.0,-24.0,26.0"] + body  # 先頭に取り込み前の残り1点、その後に長い隙間
    d, gaps = mc.longest_segment(mc.parse_csv(lines))
    assert len(d) == n and len(gaps) == 1 and gaps[0][1] > 300
    res = mc.analyze(d)
    assert not res["moving"]


def test_outlier_does_not_make_static_data_moving():
    n = 300
    xyz = np.c_[np.full(n, -2.85), np.full(n, 30.0), np.full(n, -24.9)]
    xyz[0] = (-40.0, 5.0, -24.0)  # 外れ値1点
    lines = [f"{i * 260},0x00,{x:.2f},{y:.2f},{z:.2f},19.0" for i, (x, y, z) in enumerate(xyz)]
    assert not mc.analyze(mc.parse_csv(lines))["moving"]
