#pragma once
// リアルタイム計測震度（FIRストリーミング）。
// tools/jismo/realtime.py の写経。係数は JmaFirTaps.h（tools/gen_fir_header.py で生成）。
//
// 使い方: 100Hzで push(galX,galY,galZ) を呼び続け、
// 適宜 currentIntensity() で移動窓の計測震度を得る。

#include <cstdint>

#include "JmaFirTaps.h"

class Shindo {
 public:
  static constexpr int kSampleRateHz = 100;
  static constexpr int kWindowSamples = 60 * kSampleRateHz;  // 60秒 = 6000
  static constexpr int kExceedSamples = 30;                  // 0.3秒ぶん = 30

  // hist_の固定小数点スケール（1LSB=0.1gal）。int16_tの範囲は±3276.7galで、
  // 実機センサのフルスケール（IIS3DHHC ±2452gal, ADXL355 ±2008gal、重力込み）
  // を余裕を持って収まる。
  static constexpr int kGalScale = 10;

  // composite_（フィルタ後・移動窓）専用のスケール。閾値(kAlertIntensity=0.5)
  // 付近での量子化ジッタを抑えるためkGalScaleより分解能を上げる。1LSB≈0.036gal、
  // 表現域±1170galはJMA計測震度7（a0≈1071gal）を安全に超える。ホストg++での
  // float版突き合わせで、kGalScale(0.1gal刻み)のままだと弱い揺れ(震度0.5前後)で
  // アラート閾値の跨ぎ判定が360回中最大7回ズレたが、これでもゼロにはならない
  // （閾値ジッタは分解能を上げても場所が動くだけで原理的に消えない、量子化と
  // 閾値判定の宿命）。ただし本震のような明確な超過では影響しない上、クラウド側
  // detect Lambda(閾値0.5・生データから独立に毎バッチFFT評価)が二重のセーフ
  // ティネットになるため許容している。
  static constexpr int kCompositeScale = 28;

  Shindo();

  // 1サンプル（gal単位）を投入。フィルタ後の合成加速度[gal]を返す。
  float push(float galX, float galY, float galZ);

  // 移動窓の現在の計測震度（気象庁丸め後）。データ不足なら 0。
  float currentIntensity();

  // 直近のフィルタ後合成加速度ピーク[gal]（クールダウン管理などに）。
  float lastComposite() const { return lastComposite_; }

  // 起動直後のフィルタ過渡が抜けたか（抜けるまで震度は0を返す）。
  bool warmedUp() const { return seen_ > kWarmupSamples; }

 private:
  // 段差応答は numtaps サンプルで通過しきる。それ+1秒ぶんを捨てる。
  static constexpr int kWarmupSamples = kJmaFirNumTaps + kSampleRateHz;

  float firStep(int axis, float sample);

  // 各軸のFIR履歴（循環バッファ）。int16固定小数点（kGalScale）で保持し、
  // float版の半分(6132B→3066B)にする。畳み込みはtaps[k]*hist[]をkGalScale倍
  // されたまま積算し、最後に一度だけ割って戻す。
  int16_t hist_[3][kJmaFirNumTaps];
  int histPos_[3];

  // フィルタ後合成加速度の移動窓。int16固定小数点(kCompositeScale、24000B→12000B)。
  int16_t composite_[kWindowSamples];
  int compPos_;
  int compCount_;

  long seen_;  // 投入サンプル総数（ウォームアップ判定用）
  float lastComposite_;
};
