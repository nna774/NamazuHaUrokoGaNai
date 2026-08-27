// PMW3360DM(ゲーミングマウス用オプティカルセンサ) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2「質量-バネ系+オプティカルフローピックアップ」phase0の
// 接写(数mm)側候補。PMW3901と原理・注意点(錘側に付けて初めて意味を持つ)は同じ。
// WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他。使い方は
// firmware/README.md参照）。
//
// ライブラリ: SunjunKim/PMW3360（DIYマウス界隈の定番実装、SPI）。
//
// 電圧注意: 多くのAliExpress等の基板は3.3-5V入力・ロジック3.3V対応と謳われているが
// 個体差があるので、初回はテスターで基板側のロジック電圧を確認してからESP32(3.3V
// ロジック、5V非耐性)に繋ぐこと。5V専用と分かった基板ならレベルシフタを挟む。
//
// 配線（無印ESP32 DevKitでの既定VSPIピン。TTGO T-Display等TFT搭載機で試すなら
// firmware/README.md「配線」の空きピン表に従って読み替えること。PMW3901と同じ
// バスを共有できるが同時には焼かないので配線はどちらか1系統でよい）:
//   VCC -> 3.3V, GND -> GND, MOSI -> GPIO23, MISO -> GPIO19, SCK -> GPIO18, SS -> GPIO5
#include <Arduino.h>
#include <PMW3360.h>

namespace {
constexpr int kSsPin = 5;
PMW3360 sensor;
// 小振幅の変位を検知したいのでデフォルト800より高めに設定（最大12000、感度重視）。
constexpr unsigned int kCpi = 8000;
constexpr uint32_t kSampleIntervalMs = 10;
}  // namespace

void setup() {
  Serial.begin(115200);
  if (sensor.begin(kSsPin, kCpi)) {
    Serial.println("# PMW3360 init ok");
  } else {
    Serial.println("# PMW3360 init failed");
  }
  Serial.println("# t_ms,isMotion,isOnSurface,dx,dy,SQUAL,shutter");
}

void loop() {
  static uint32_t next_ms = millis();
  uint32_t now = millis();
  if (static_cast<int32_t>(now - next_ms) < 0) return;
  next_ms += kSampleIntervalMs;

  PMW3360_DATA data = sensor.readBurst();
  Serial.printf("%lu,%d,%d,%d,%d,%u,%u\n", static_cast<unsigned long>(now), data.isMotion,
                data.isOnSurface, data.dx, data.dy, data.SQUAL, data.shutter);
}
