#pragma once
// 30秒ぶんの 3軸サンプルを貯めてワイヤ形式にする可変長バッファ。
// 1サンプルの幅は sampleFormat で決まる（0=int16 6B / 1=int32 12B）。

#include <cstdint>
#include <cstdlib>

#include "WireFormat.h"

class Batch {
 public:
  // capacitySamples ぶんの領域を確保する。失敗時 valid()==false。
  // sampleFormat は AccelSensor::sampleFormat() をそのまま渡す（0=int16, 1=int32）。
  explicit Batch(uint32_t capacitySamples, uint8_t sampleFormat = 0);
  ~Batch();

  Batch(const Batch&) = delete;
  Batch& operator=(const Batch&) = delete;

  bool valid() const { return buf_ != nullptr; }

  // 先頭サンプルの時刻とセンサ諸元を設定（1サンプル目投入前に呼ぶ）。
  // sample_format はバッファ確保時に決まっているのでここでは受け取らない。
  void begin(uint64_t startUs, uint8_t sensorType, float scaleMgPerLsb,
             uint32_t sampleRateHz, uint32_t deviceId);

  // 1サンプル追加。満杯なら false。
  // int16 フォーマットのときは範囲外の値が飽和ではなく切り詰めになるので、
  // センサ側の scaleMgPerLsb で int16 に収まることを保証しておくこと。
  bool addSample(int32_t x, int32_t y, int32_t z);

  bool isFull() const { return count_ >= capacity_; }
  uint32_t count() const { return count_; }
  uint64_t startUs() const { return startUs_; }

  // ヘッダの sample_count を確定し、送信用バイト列を返す。
  const uint8_t* bytes();
  size_t size() const {
    return fixedSize_ ? fixedSize_ : kWireHeaderSize + count_ * sampleBytes_;
  }

  // 退避ファイルから復元（バイト列を丸ごと保持）。
  static Batch* fromBytes(const uint8_t* data, size_t len);

 private:
  Batch() = default;  // fromBytes 用
  static size_t sampleBytesFor(uint8_t sampleFormat) {
    return sampleFormat == 1 ? 3 * sizeof(int32_t) : 3 * sizeof(int16_t);
  }

  uint8_t* buf_ = nullptr;
  uint8_t sampleFormat_ = 0;
  size_t sampleBytes_ = 3 * sizeof(int16_t);
  uint32_t capacity_ = 0;
  uint32_t count_ = 0;
  uint64_t startUs_ = 0;
  size_t fixedSize_ = 0;  // fromBytes で確定サイズを持つ場合
};
