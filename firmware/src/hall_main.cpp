// SS49E(アナログ出力ホール素子) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2 の「質量-バネ系+磁気ピックアップ」phase0:
// まずセンサ単体が磁石の接近に反応するかだけを見る。WiFi/送信/NVSは一切使わない
// （main.cppとはsetup()/loop()が排他なので、platformio.iniの
// [env:hall-bringup](無印ESP32)・[env:hall-bringup-c3](ESP32-C3 SuperMini)で
// このファイルだけをビルドする。使い方はfirmware/README.md参照）。
//
// 配線:
//   無印ESP32 DevKit: SS49E VCC -> 3.3V, GND -> GND, OUT -> GPIO34 (ADC1_CH6、入力専用ピン)
//   ESP32-C3 SuperMini: OUT -> GPIO3 (ADC1、GPIO2はストラップピン・GPIO9はBOOTボタン
//     専有なので両方避けてある——これはチップ仕様なので基板の印字順によらず共通)。
//     図解: docs/img/ss49e-esp32c3-wiring.svg（2026-08-27に実機写真で確認した
//     この個体の実物ピン配置。docs/piezo.md §4のピエゾ機とは印字の並び順が異なる
//     別個体なので、GPIO3の物理位置はそちらの表とは一致しない点に注意）。
//     SS49E本体には印字が無いため、Honeywell datasheet(SS39ET/SS49E/SS59ET
//     Series)Figure 4「SS49E」のリード配置図から同定: フラット面(N/S矢印面)を
//     手前に・リードを下向きにして見た状態で左から +(VCC) / −(GND) / 0(OUTPUT)。
//   TTGO T-Display等TFT搭載機で無印ESP32環境を使うなら
//   firmware/README.md「配線」の空きピン表に従って読み替えること。
//
// SS49Eは方向(N/S)で出力が中点(無磁場時 約VCC/2)から上下する。机上確認では
// 磁石をゆっくり近づけ/遠ざけて、raw値が中点から動くこと・戻ることを見ればよい。
#include <Arduino.h>

namespace {
#ifdef CONFIG_IDF_TARGET_ESP32C3
constexpr int kHallPin = 3;
#else
constexpr int kHallPin = 34;
#endif
constexpr float kAdcMaxCount = 4095.0f;
constexpr float kAdcRefVolts = 3.3f;
// 2kHz。アーム共振の確認(想定30〜50Hz帯を5〜10倍オーバーサンプリングして
// リンギング波形を読み取る用途)向けに、磁石接近確認用の100Hzから引き上げた。
constexpr uint32_t kSampleIntervalUs = 500;
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
  // USB CDC送信バッファが埋まっていると Serial.printf() はバッファに空きが
  // できるまでブロックし、その間loop()が止まってウォッチドッグに落とされる
  // (2026-08-28、tools/live_scope.py側の読み出しが詰まった時に実機で発生)。
  // 2kHzだと詰まりやすいので、書ける分だけ空いているか先に確認し、
  // 空いていなければブロックせずこのサンプルを捨てる。
  char line[40];
  int len = snprintf(line, sizeof(line), "%lu,%d,%.4f\n", static_cast<unsigned long>(now), raw, volts);
  if (len > 0 && Serial.availableForWrite() >= len) {
    Serial.write(reinterpret_cast<const uint8_t*>(line), len);
  }
}
