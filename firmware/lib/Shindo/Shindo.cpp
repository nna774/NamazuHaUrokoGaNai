#include "Shindo.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <utility>

Shindo::Shindo() : compPos_(0), compCount_(0), seen_(0), lastComposite_(0.0f) {
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

  // ウォームアップ中はフィルタ過渡なので移動窓に入れない。
  ++seen_;
  if (seen_ > kWarmupSamples) {
    composite_[compPos_] = comp;
    if (++compPos_ >= kWindowSamples) compPos_ = 0;
    if (compCount_ < kWindowSamples) ++compCount_;
  }

  lastComposite_ = comp;
  return comp;
}

namespace {
// サイズkExceedSamplesの最小ヒープ。currentIntensity()が「上位kExceedSamples個の
// うち最小の値」だけを求めるための補助（heap[0]が常に最小）。
void siftDown(float* heap, int size, int i) {
  for (;;) {
    int l = 2 * i + 1, r = 2 * i + 2, smallest = i;
    if (l < size && heap[l] < heap[smallest]) smallest = l;
    if (r < size && heap[r] < heap[smallest]) smallest = r;
    if (smallest == i) break;
    std::swap(heap[i], heap[smallest]);
    i = smallest;
  }
}
}  // namespace

float Shindo::currentIntensity() {
  if (compCount_ < kExceedSamples) return 0.0f;

  // composite_は循環バッファで、compPos_（次に上書きされる=最古の位置）以外の
  // 並び順に意味は無い……はずが、nth_elementでcomposite_自体を並び替えると
  // 「compPos_=最古」という前提が崩れてFIFO退避が壊れる（この位置に元あった
  // 最古値がnth_elementで別の位置へ移動してしまい、次回pushが新しい値でない
  // 値を上書きしてしまう）。実測で震度計算が食い違うことを確認済み。
  // 欲しいのは「上位kExceedSamples個のうち最小の値」だけなので、6000要素の
  // コピー(24000B、compositeとほぼ同サイズの静的バッファ)は不要。
  // composite_を読み取り専用のまま、サイズkExceedSamples(30個=120B)の
  // 最小ヒープで一回走査すれば足りる。
  float heap[kExceedSamples];
  int size = 0;
  int n = compCount_;
  for (int i = 0; i < n; ++i) {
    float v = composite_[i];
    if (size < kExceedSamples) {
      heap[size++] = v;
      if (size == kExceedSamples) {
        for (int j = kExceedSamples / 2 - 1; j >= 0; --j) siftDown(heap, size, j);
      }
    } else if (v > heap[0]) {
      heap[0] = v;
      siftDown(heap, size, 0);
    }
  }
  float a0 = heap[0];
  if (a0 <= 0.0f) return 0.0f;

  float raw = 2.0f * std::log10(a0) + 0.94f;
  // 気象庁丸め: 小数第3位四捨五入 -> 小数第2位切り捨て
  float two = std::floor(raw * 100.0f + 0.5f) / 100.0f;
  return std::floor(two * 10.0f) / 10.0f;
}
