#include "Shindo.h"

#include <algorithm>
#include <cmath>
#include <cstring>

Shindo::Shindo() : compPos_(0), compCount_(0), lastComposite_(0.0f) {
  std::memset(hist_, 0, sizeof(hist_));
  std::memset(histPos_, 0, sizeof(histPos_));
  std::memset(composite_, 0, sizeof(composite_));
}

float Shindo::firStep(int axis, float sample) {
  int pos = histPos_[axis];
  hist_[axis][pos] = sample;
  // y[n] = sum_k taps[k] * x[n-k]
  double acc = 0.0;
  int idx = pos;
  for (int k = 0; k < kJmaFirNumTaps; ++k) {
    acc += static_cast<double>(kJmaFirTaps[k]) * hist_[axis][idx];
    if (--idx < 0) idx = kJmaFirNumTaps - 1;
  }
  if (++pos >= kJmaFirNumTaps) pos = 0;
  histPos_[axis] = pos;
  return static_cast<float>(acc);
}

float Shindo::push(float galX, float galY, float galZ) {
  float fx = firStep(0, galX);
  float fy = firStep(1, galY);
  float fz = firStep(2, galZ);
  float comp = std::sqrt(fx * fx + fy * fy + fz * fz);

  composite_[compPos_] = comp;
  if (++compPos_ >= kWindowSamples) compPos_ = 0;
  if (compCount_ < kWindowSamples) ++compCount_;

  lastComposite_ = comp;
  return comp;
}

float Shindo::currentIntensity() {
  if (compCount_ < kExceedSamples) return 0.0f;

  // 移動窓のコピーを取り、kExceedSamples 番目に大きい値(a0)を求める。
  static float tmp[kWindowSamples];
  std::memcpy(tmp, composite_, sizeof(float) * compCount_);

  // 上位 kExceedSamples 個を後方に集める -> その先頭が「30番目に大きい値」
  int n = compCount_;
  int kth = n - kExceedSamples;  // nth_element の分割位置
  std::nth_element(tmp, tmp + kth, tmp + n);
  float a0 = tmp[kth];
  if (a0 <= 0.0f) return 0.0f;

  float raw = 2.0f * std::log10(a0) + 0.94f;
  // 気象庁丸め: 小数第3位四捨五入 -> 小数第2位切り捨て
  float two = std::floor(raw * 100.0f + 0.5f) / 100.0f;
  return std::floor(two * 10.0f) / 10.0f;
}
