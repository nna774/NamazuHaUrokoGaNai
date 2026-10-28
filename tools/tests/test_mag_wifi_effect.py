import numpy as np

import mag_wifi_effect as mw


def _csv(delta_x=0.0, cycles=5, win_s=20, dt=0.26, drift_x_per_s=0.0, seed=0):
    rng = np.random.default_rng(seed)
    lines = ["# t_ms,status,x_uT,y_uT,z_uT,temp_C,phase"]
    t = 0.0
    for k in range(cycles * 2):
        phase = k % 2
        for _ in range(int(win_s / dt)):
            x = -2.85 + drift_x_per_s * t + (delta_x if phase == 1 else 0.0) + rng.normal(0, 0.2)
            lines.append(f"{int(t * 1000)},0x00,{x:.3f},{30 + rng.normal(0, .2):.3f},{-24.9 + rng.normal(0, .3):.3f},19.0,{phase}")
            t += dt
    return lines


def test_detects_step_in_scan_windows():
    res = mw.effect(mw.split_windows(mw.parse_csv(_csv(delta_x=0.5)), 4.0))
    assert res["n_pairs"] == 4
    assert abs(res["mean"][0] - 0.5) < 0.1
    assert abs(res["mean"][1]) < 0.1
    assert "有意" in mw.report(res, 21.2).splitlines()[1]


def test_no_effect_is_not_significant_and_linear_drift_cancels():
    res = mw.effect(mw.split_windows(mw.parse_csv(_csv(delta_x=0.0, drift_x_per_s=0.005)), 4.0))
    assert abs(res["mean"][0]) < 0.1  # 0.005µT/s×40s=0.2µT/周期のドリフトは前後平均で相殺される
    assert "有意でない" in mw.report(res, 21.2).splitlines()[1]


def test_parse_skips_status_and_short_rows():
    d = mw.parse_csv(["1000,0x00,1,2,3,19.0,1", "1000,0x04,1,2,3,19.0,1", "1000,0x00,1,2,3,19.0", "x"])
    assert d.shape == (1, 6)
