"""device3(ピエゾ、Z軸)の回路+機械共振+ADCサンプリングを通した簡易シミュレーション。

docs/piezo.md §9・docs/log/2026-08-15-piezo-oversampling-boxcar-consideration.md
参照。以下を検算するために書いた:

1. 1-10Hz帯の地震動が来た時、Z軸の回路(保護回路+アンチエイリアシングローパス)と
   fs=100Hzサンプリングを通すとADC上でどんな波形になるか
2. 本線(main.cpp)と同じ1kHzオーバーサンプリング+ボックスカー10平均を併用したら
   共振(約50Hz、ナイキスト直下)のエイリアシングがどう変わるか

未校正センサのため、入力加速度・ピエゾ感度(kappa)は目安のスケール定数で
調整しているだけで、絶対値に意味は無い。信頼していいのは波形の「形」と
「フィルタ・オーバーサンプリング有無の相対比較」。

使い方:
    .venv/bin/python tools/piezo_lowpass_sim.py --out-dir docs/log/img
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy import signal

# --- 実測・設計値(docs/piezo.md参照) ---
F0 = 49.947          # 実測固有周波数 [Hz] (§5)
ZETA = 0.10          # 減衰比(推定、"3-4周期で減衰"の目視観察から逆算)
RB = 10e6            # バイアス抵抗 [ohm] (§4)
C1 = 20e-9           # ピエゾ本体の静電容量(仮定・未実測) [F] (§4)
RS = 47e3            # 直列抵抗 [ohm] (§4)
C2_NOW = 100e-9      # 現在の実装値(2026-08-15〜) [F] (§9)
DT_SIM = 1.0 / 4000  # シミュレーション内部の時間刻み(50Hz共振を十分解像する)


def mechanical_system() -> signal.StateSpace:
    """地動加速度 a(t) -> 片持ち梁の相対変位 z(t)。

    z'' + 2*zeta*w0*z' + w0^2*z = -a(t)  (地震計の標準的な運動方程式)
    """
    w0 = 2 * np.pi * F0
    A = np.array([[0, 1], [-w0**2, -2 * ZETA * w0]])
    B = np.array([[0], [-1]])
    C = np.array([[1, 0]])
    D = np.array([[0]])
    return signal.StateSpace(A, B, C, D)


def electrical_system(c2: float) -> signal.StateSpace:
    """電荷源電流 I_in(t) -> Node B電圧 V_B(t)。C2ありの2ノード回路。

    Node A: I_in = C1*dVA/dt + VA/Rb + (VA-VB)/Rs
    Node B: (VA-VB)/Rs = C2*dVB/dt
    """
    a11 = -(1 / RB + 1 / RS) / C1
    a12 = (1 / RS) / C1
    a21 = (1 / RS) / c2
    a22 = -(1 / RS) / c2
    A = np.array([[a11, a12], [a21, a22]])
    B = np.array([[1 / C1], [0]])
    C = np.array([[0, 1]])
    D = np.array([[0]])
    return signal.StateSpace(A, B, C, D)


def electrical_system_no_c2() -> signal.StateSpace:
    """C2を入れる前の回路。Rsの先は実質開放なのでV_B≈V_A。"""
    a11 = -(1 / RB) / C1
    A = np.array([[a11]])
    B = np.array([[1 / C1]])
    C = np.array([[1]])
    D = np.array([[0]])
    return signal.StateSpace(A, B, C, D)


def synth_earthquake(t: np.ndarray, scale_gal: float, seed: int = 42) -> np.ndarray:
    """1-10Hz帯のS波風バースト + P波初動インパルスを合成する。"""
    rng = np.random.default_rng(seed)
    n = len(t)
    env = np.zeros(n)
    t_onset, rise, decay_tau = 2.0, 0.3, 3.0
    for i, ti in enumerate(t):
        if ti < t_onset:
            env[i] = 0
        elif ti < t_onset + rise:
            env[i] = (ti - t_onset) / rise
        else:
            env[i] = np.exp(-(ti - t_onset - rise) / decay_tau)

    freqs = [2.3, 3.7, 5.1, 7.2]
    accel = np.zeros(n)
    for f in freqs:
        phase = rng.uniform(0, 2 * np.pi)
        accel += np.sin(2 * np.pi * f * t + phase) / len(freqs)
    accel *= env

    # P波初動: 立ち上がり直後の鋭いインパルス(構造物の高次共振を叩き起こす)
    impulse_idx = int(t_onset / DT_SIM)
    impulse_width = int(0.01 / DT_SIM)
    accel[impulse_idx:impulse_idx + impulse_width] += 3.0 * signal.windows.hann(impulse_width)

    return accel * scale_gal


def piezo_response(accel: np.ndarray, t: np.ndarray, kappa: float):
    """地動加速度 -> 機械応答 -> ピエゾ電流源I_in、C2有り/無しのV_Bを返す。"""
    _, z, _ = signal.lsim(mechanical_system(), accel, t)
    i_in = kappa * np.gradient(z, DT_SIM)
    _, vb_with, _ = signal.lsim(electrical_system(C2_NOW), i_in, t)
    _, vb_without, _ = signal.lsim(electrical_system_no_c2(), i_in, t)
    return vb_with, vb_without


ADC_LSB = 3.3 / (2 ** 12)
ADC_BIAS_COUNTS = 270  # 実測の静穏時DC動作点とオーダーを合わせる


def sample_100hz_direct(vb: np.ndarray, t: np.ndarray, noise_std: float, seed: int = 1):
    idx = np.arange(0, len(t), int(round((1 / 100.0) / DT_SIM)))
    rng = np.random.default_rng(seed)
    counts = ADC_BIAS_COUNTS + vb[idx] / ADC_LSB + rng.normal(0, noise_std, len(idx))
    return t[idx], np.clip(counts, 0, 2**12 - 1)


def sample_1khz_boxcar(vb: np.ndarray, t: np.ndarray, noise_std: float, oversample: int = 10, seed: int = 1):
    """本線と同じkOversample=10: 1kHzで読み、10サンプル平均して100Hzに間引く。"""
    idx_1k = np.arange(0, len(t), int(round((1 / 1000.0) / DT_SIM)))
    rng = np.random.default_rng(seed)
    raw = ADC_BIAS_COUNTS + vb[idx_1k] / ADC_LSB + rng.normal(0, noise_std, len(idx_1k))
    raw = np.clip(raw, 0, 2**12 - 1)
    m = (len(raw) // oversample) * oversample
    avg = raw[:m].reshape(-1, oversample).mean(axis=1)
    t_out = t[idx_1k][:m].reshape(-1, oversample).mean(axis=1)
    return t_out, avg


def _setup_japanese_font():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    fm.fontManager.addfont("/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Hiragino Sans"
    return plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="docs/log/img")
    parser.add_argument("--scale-gal", type=float, default=8.0 * 15,
                         help="合成地震波の振幅目安(未校正)")
    parser.add_argument("--kappa", type=float, default=4e-6,
                         help="ピエゾ感度の目安定数(未校正)")
    parser.add_argument("--noise-std", type=float, default=10.0,
                         help="実測の静穏時ADCノイズstdev目安")
    args = parser.parse_args()

    plt = _setup_japanese_font()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = 12.0
    t = np.arange(0, duration, DT_SIM)
    accel = synth_earthquake(t, args.scale_gal)
    vb_with, vb_without = piezo_response(accel, t, args.kappa)

    t_onset = 2.0

    # --- 図1: 全体像(地動加速度・ADC波形・共振リンギング拡大・静穏帯との比較) ---
    fig, axes = plt.subplots(4, 1, figsize=(11, 13))

    t_a100, c_without_100 = sample_100hz_direct(vb_without, t, args.noise_std)
    t_b100, c_with_100 = sample_100hz_direct(vb_with, t, args.noise_std)

    ax = axes[0]
    ax.plot(t, accel, color="#444", lw=1)
    ax.set_title("① 合成地動加速度 a(t)  [1-10Hz帯のS波風バースト + P波初動インパルス] (未校正・目安スケール)")
    ax.set_ylabel("加速度 (arb.)")
    ax.axvspan(t_onset, t_onset + 0.05, color="orange", alpha=0.3, label="P波初動(インパルス)")
    ax.legend(loc="upper right", fontsize=8)

    ax = axes[1]
    ax.plot(t_a100, c_without_100, color="#c0392b", lw=0.7, label="ローパス無し(実装前の回路)")
    ax.plot(t_b100, c_with_100, color="#2166ac", lw=0.9, label="ローパス有り(C=100nF、現行)")
    ax.set_title("② ADCサンプリング後の波形(fs=100Hz、12bit) — フィルタ有無の比較")
    ax.set_ylabel("ADCカウント")
    ax.axhline(4095, color="gray", ls="--", lw=0.7)
    ax.axhline(0, color="gray", ls="--", lw=0.7)
    ax.legend(loc="upper right", fontsize=8)

    ax = axes[2]
    mask_a = (t_a100 > t_onset - 0.05) & (t_a100 < t_onset + 0.6)
    mask_b = (t_b100 > t_onset - 0.05) & (t_b100 < t_onset + 0.6)
    ax.plot(t_a100[mask_a], c_without_100[mask_a], color="#c0392b", marker="o", ms=3, lw=0.8, label="ローパス無し")
    ax.plot(t_b100[mask_b], c_with_100[mask_b], color="#2166ac", marker="o", ms=3, lw=0.8, label="ローパス有り(C=100nF)")
    ax.set_title("③ ②の拡大: P波初動直後(共振リンギングが出る区間)")
    ax.set_ylabel("ADCカウント")
    ax.legend(loc="upper right", fontsize=8)

    ax = axes[3]
    quiet_band = 3 * args.noise_std
    ax.axhspan(ADC_BIAS_COUNTS - quiet_band, ADC_BIAS_COUNTS + quiet_band, color="#7fbf7f", alpha=0.3,
               label="実測の静穏時ベースライン(±3σ、2026-08-15夜のC=100nF実データ基準)")
    ax.plot(t_b100, c_with_100, color="#2166ac", lw=0.9, label="今回のシミュレーション(ローパス有り)")
    ax.set_title("④ 静穏時の実測ノイズ帯 vs 今回の合成地震波形(ローパス有り)")
    ax.set_xlabel("時刻 [s]")
    ax.set_ylabel("ADCカウント")
    ax.legend(loc="upper right", fontsize=8)

    for a in axes:
        a.grid(alpha=0.3)

    fig.suptitle("ピエゾ(Z軸)シミュレーション: 1-10Hz地震波 + 50Hz共振励起 + ADC(fs=100Hz)\n"
                 "※ 未校正センサのため縦軸・入力振幅は目安。波形の形・フィルタ有無の相対比較が主眼",
                 fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_dir / "2026-08-15-piezo-earthquake-sim.png", dpi=140)
    plt.close(fig)

    # --- 図2: 1kHzオーバーサンプリング+ボックスカー10平均との比較 ---
    t_a1k, c_without_1k = sample_1khz_boxcar(vb_without, t, args.noise_std)
    t_b1k, c_with_1k = sample_1khz_boxcar(vb_with, t, args.noise_std)

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    ax = axes[0]
    mask_c = (t_a1k > t_onset - 0.05) & (t_a1k < t_onset + 0.6)
    ax.plot(t_a100[mask_a], c_without_100[mask_a], color="#c0392b", marker="o", ms=3, lw=0.8,
            label="C2無し・100Hz直接(現状比較用の最悪ケース)")
    ax.plot(t_a1k[mask_c], c_without_1k[mask_c], color="#e67e22", marker="s", ms=3, lw=0.8,
            label="C2無し・1kHz+ボックスカー10平均→100Hz")
    ax.set_title("① C2(アナログローパス)を入れない場合: 100Hz直接 vs 1kHz+ボックスカー平均")
    ax.set_ylabel("ADCカウント")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[1]
    mask_d = (t_b1k > t_onset - 0.05) & (t_b1k < t_onset + 0.6)
    ax.plot(t_b100[mask_b], c_with_100[mask_b], color="#2166ac", marker="o", ms=3, lw=0.8,
            label="C2=100nF・100Hz直接(現行ファーム相当)")
    ax.plot(t_b1k[mask_d], c_with_1k[mask_d], color="#27ae60", marker="s", ms=3, lw=0.8,
            label="C2=100nF・1kHz+ボックスカー10平均→100Hz(併用)")
    ax.set_title("② C2(アナログローパス、現行)を入れた場合: 100Hz直接 vs 1kHz+ボックスカー併用")
    ax.set_ylabel("ADCカウント")
    ax.set_xlabel("時刻 [s]")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

    fig.suptitle("本線と同じ1kHzオーバーサンプリング+ボックスカー10平均を併用したらどうなるか\n"
                 "(P波初動直後・共振リンギング区間の拡大、未校正・目安スケール)", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out_dir / "2026-08-15-piezo-oversample-compare.png", dpi=140)
    plt.close(fig)

    def stats(name, tt, cc, t0, t1):
        m = (tt > t0) & (tt < t1)
        seg = cc[m] - ADC_BIAS_COUNTS
        print(f"{name:40s} peak={np.max(np.abs(seg)):8.1f}  rms={np.sqrt(np.mean(seg**2)):8.2f}")

    print("---- 立ち上がり直後(2.0-2.6s)の統計 ----")
    stats("C2無し・100Hz直接", t_a100, c_without_100, t_onset, t_onset + 0.6)
    stats("C2無し・1kHz+box→100Hz", t_a1k, c_without_1k, t_onset, t_onset + 0.6)
    stats("C2=100nF・100Hz直接", t_b100, c_with_100, t_onset, t_onset + 0.6)
    stats("C2=100nF・1kHz+box→100Hz", t_b1k, c_with_1k, t_onset, t_onset + 0.6)
    print(f"saved: {out_dir}/2026-08-15-piezo-earthquake-sim.png")
    print(f"saved: {out_dir}/2026-08-15-piezo-oversample-compare.png")


if __name__ == "__main__":
    main()
