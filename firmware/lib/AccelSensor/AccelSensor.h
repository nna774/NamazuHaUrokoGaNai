#pragma once
// 加速度センサの抽象インターフェイス。
// SPI先を IIS3DHHC から ADXL355 等へ差し替えてもパイプラインが壊れないようにする。

#include <cstdint>

struct AccelSample {
  int32_t x;  // 生の LSB 値（16bit センサでも int32 で受ける）
  int32_t y;
  int32_t z;
};

class AccelSensor {
 public:
  virtual ~AccelSensor() = default;

  // 初期化。成功で true。
  virtual bool begin() = 0;

  // 最新の1サンプルを読む。成功で true。
  virtual bool read(AccelSample& out) = 0;

  // 1 LSB あたりの mg（milli-g）。ワイヤフォーマットのヘッダに載せる。
  virtual float scaleMgPerLsb() const = 0;

  // ワイヤフォーマットのセンサ種別。
  virtual uint8_t sensorType() const = 0;

  // 生値のフォーマット: 0=int16, 1=int32。
  virtual uint8_t sampleFormat() const = 0;
};

// LSB -> gal(cm/s^2) 変換ヘルパ。mg * 0.980665 = gal。
inline float lsbToGal(int32_t lsb, float scaleMgPerLsb) {
  return static_cast<float>(lsb) * scaleMgPerLsb * 0.980665f;
}
