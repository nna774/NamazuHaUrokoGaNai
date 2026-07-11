#pragma once
// 30秒ぶんの int16×3軸 サンプルを貯めてワイヤ形式にする可変長バッファ。

#include <cstdint>
#include <cstdlib>

#include "WireFormat.h"

class Batch {
 public:
  // capacitySamples ぶんの領域を確保する。失敗時 valid()==false。
  explicit Batch(uint32_t capacitySamples);
  ~Batch();

  Batch(const Batch&) = delete;
  Batch& operator=(const Batch&) = delete;

  bool valid() const { return buf_ != nullptr; }

  // 先頭サンプルの時刻とセンサ諸元を設定（1サンプル目投入前に呼ぶ）。
  void begin(uint64_t startUs, uint8_t sensorType, uint8_t sampleFormat,
             float scaleMgPerLsb, uint32_t sampleRateHz, uint32_t deviceId);

  // 1サンプル追加。満杯なら false。
  bool addSample(int16_t x, int16_t y, int16_t z);

  bool isFull() const { return count_ >= capacity_; }
  uint32_t count() const { return count_; }
  uint64_t startUs() const { return startUs_; }

  // ヘッダの sample_count を確定し、送信用バイト列を返す。
  const uint8_t* bytes();
  size_t size() const {
    return fixedSize_ ? fixedSize_ : kWireHeaderSize + count_ * kSampleBytes;
  }

  // 退避ファイルから復元（バイト列を丸ごと保持）。
  static Batch* fromBytes(const uint8_t* data, size_t len);

 private:
  Batch() = default;  // fromBytes 用
  static constexpr size_t kSampleBytes = 3 * sizeof(int16_t);

  uint8_t* buf_ = nullptr;
  uint32_t capacity_ = 0;
  uint32_t count_ = 0;
  uint64_t startUs_ = 0;
  size_t fixedSize_ = 0;  // fromBytes で確定サイズを持つ場合
};
