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

  Shindo();

  // 1サンプル（gal単位）を投入。フィルタ後の合成加速度[gal]を返す。
  float push(float galX, float galY, float galZ);

  // 移動窓の現在の計測震度（気象庁丸め後）。データ不足なら 0。
  float currentIntensity();

  // 直近のフィルタ後合成加速度ピーク[gal]（クールダウン管理などに）。
  float lastComposite() const { return lastComposite_; }

 private:
  float firStep(int axis, float sample);

  // 各軸のFIR履歴（循環バッファ）
  float hist_[3][kJmaFirNumTaps];
  int histPos_[3];

  // フィルタ後合成加速度の移動窓
  float composite_[kWindowSamples];
  int compPos_;
  int compCount_;

  float lastComposite_;
};
