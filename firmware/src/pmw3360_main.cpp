// PMW3360DM(ゲーミングマウス用オプティカルセンサ) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2「質量-バネ系+オプティカルフローピックアップ」phase0の
// 接写(数mm)側候補。PMW3901と原理・注意点(錘側に付けて初めて意味を持つ)は同じ。
// WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他。
// [env:pmw3360-bringup](無印ESP32)・[env:pmw3360-bringup-c3](ESP32-C3 SuperMini)。
// 使い方はfirmware/README.md参照）。
//
// ライブラリ: SunjunKim/PMW3360（DIYマウス界隈の定番実装、SPI）。begin()内部は
// `SPI.begin()`を引数無しで呼ぶだけだが、ESP32のSPIClass::begin()は既にバスが
// 開始済みなら何もせず戻る実装なので、下記のように先にカスタムピンでSPI.begin()
// しておけばそちらが優先される。
//
// 電圧注意: 多くのAliExpress等の基板は3.3-5V入力・ロジック3.3V対応と謳われているが
// 個体差があるので、初回はテスターで基板側のロジック電圧を確認してからESP32(3.3V
// ロジック、5V非耐性)に繋ぐこと。5V専用と分かった基板ならレベルシフタを挟む。
//
// 配線（PMW3901と同じバスを共有できるが同時には焼かないので配線はどちらか1系統でよい）:
//   無印ESP32 DevKit(既定VSPIピン): VCC -> 3.3V, GND -> GND,
//     MOSI -> GPIO23, MISO -> GPIO19, SCK -> GPIO18, SS -> GPIO5
//     （TTGO T-Display等TFT搭載機で試すならfirmware/README.md「配線」の
//     空きピン表に従って読み替えること）
//   ESP32-C3 SuperMini: SCK -> GPIO4, MISO -> GPIO5, MOSI -> GPIO6, SS -> GPIO7
//     （docs/piezo.md §4のピン配置表のうち、GPIO2/GPIO9(ストラップ・BOOT)を避けた空きピン）
#include <Arduino.h>
#include <PMW3360.h>
#include <SPI.h>

namespace {
#ifdef CONFIG_IDF_TARGET_ESP32C3
constexpr int kSckPin = 4;
constexpr int kMisoPin = 5;
constexpr int kMosiPin = 6;
constexpr int kSsPin = 7;
#else
constexpr int kSsPin = 5;
#endif
PMW3360 sensor;
// 小振幅の変位を検知したいのでデフォルト800より高めに設定（最大12000、感度重視）。
constexpr unsigned int kCpi = 8000;
constexpr uint32_t kSampleIntervalMs = 10;
}  // namespace

void setup() {
  Serial.begin(115200);
#ifdef CONFIG_IDF_TARGET_ESP32C3
  SPI.begin(kSckPin, kMisoPin, kMosiPin, kSsPin);
#endif
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
