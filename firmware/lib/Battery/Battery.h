#pragma once
// UPS(LFUPSMA)のB+/B-から分圧で取り出した電池電圧をESP32 ADC1で読む
// (docs/img/ups-battery-adc-wiring.svg、docs/ups.md §4)。
// analogReadMilliVolts()はArduino-ESP32コア内蔵のeFuse較正(Two Point/Vref)込みの
// 実効mVを返すため、esp_adc_cal を直接叩く必要はない。

#include <Arduino.h>

namespace battery {

// setup()から一度だけ、ピン番号を渡して呼ぶ。
inline void begin(int pin) {
  analogSetPinAttenuation(pin, ADC_11db);
}

// 分圧前の電池電圧[mV]を返す。oversampleサンプル平均してノイズを均す
// （測定はブロッキングだが1回あたり数百µs級、Core0のuploaderTaskループに
// 差し込む分には無視できる）。
inline uint32_t readMillivolts(int pin, float dividerRatio, int oversample = 64) {
  uint32_t sum = 0;
  for (int i = 0; i < oversample; ++i) {
    sum += analogReadMilliVolts(pin);
  }
  return (uint32_t)((float)sum / oversample * dividerRatio);
}

}  // namespace battery
