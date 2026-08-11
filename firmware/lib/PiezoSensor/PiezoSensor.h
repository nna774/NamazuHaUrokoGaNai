#pragma once
// ピエゾ素子(圧電ブザー)をADCで読む。docs/piezo.md 参照。
// 校正しない・タイミング一致だけを狙う非校正センサ(RawSensor)の実装。

#include <Arduino.h>

#include "RawSensor.h"

class PiezoSensor : public RawSensor {
 public:
  // sensorType: docs/wire_format.md「sensor_type の帯域」の非校正センサ帯(128〜249)。
  explicit PiezoSensor(int pin, uint8_t sensorType) : pin_(pin), sensorType_(sensorType) {}

  bool begin() override {
    analogSetAttenuation(ADC_11db);  // フルスケール(~0-3.3V)を使う
    return true;
  }

  bool read(int32_t* out) override {
    out[0] = analogRead(pin_);
    return true;
  }

  uint8_t axes() const override { return 1; }
  uint8_t sensorType() const override { return sensorType_; }
  uint8_t sampleFormat() const override { return 0; /* int16、ADC分解能は12bitで収まる */ }

 private:
  int pin_;
  uint8_t sensorType_;
};
