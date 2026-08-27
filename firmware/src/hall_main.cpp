// SS49E(アナログ出力ホール素子) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2 の「質量-バネ系+磁気ピックアップ」phase0:
// まずセンサ単体が磁石の接近に反応するかだけを見る。WiFi/送信/NVSは一切使わない
// （main.cppとはsetup()/loop()が排他なので、platformio.iniの[env:hall-bringup]で
// このファイルだけをビルドする。使い方はfirmware/README.md参照）。
//
// 配線（無印ESP32 DevKitでの既定。TTGO T-Display等TFT搭載機で試すなら
// firmware/README.md「配線」の空きピン表に従って読み替えること）:
//   SS49E VCC -> 3.3V, GND -> GND, OUT -> GPIO34 (ADC1_CH6、入力専用ピン)
//
// SS49Eは方向(N/S)で出力が中点(無磁場時 約VCC/2)から上下する。机上確認では
// 磁石をゆっくり近づけ/遠ざけて、raw値が中点から動くこと・戻ることを見ればよい。
#include <Arduino.h>

namespace {
constexpr int kHallPin = 34;
constexpr float kAdcMaxCount = 4095.0f;
constexpr float kAdcRefVolts = 3.3f;
constexpr uint32_t kSampleIntervalUs = 10000;  // 100Hz。phase0の確認には十分速い
}  // namespace

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  Serial.println("# t_us,raw,volts");
}

void loop() {
  static uint32_t next_us = micros();
  uint32_t now = micros();
  if (static_cast<int32_t>(now - next_us) < 0) return;
  next_us += kSampleIntervalUs;

  int raw = analogRead(kHallPin);
  float volts = raw / kAdcMaxCount * kAdcRefVolts;
  Serial.printf("%lu,%d,%.4f\n", static_cast<unsigned long>(now), raw, volts);
}
