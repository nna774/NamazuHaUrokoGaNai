// PMW3901(オプティカルフローセンサ、ドローン用) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2「質量-バネ系+オプティカルフローピックアップ」phase0。
// 錘に取り付けてフレーム固定面を見て初めて意味を持つ方式（フレーム側に固定して
// 床や壁を見る使い方は不可、という同§3.1の注意を忘れずに——机上確認の段階では
// とりあえず手近な模様の上で動かして反応するかだけ見ればよい）。
// WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他。
// [env:pmw3901-bringup](無印ESP32)・[env:pmw3901-bringup-c3](ESP32-C3 SuperMini)。
// 使い方はfirmware/README.md参照）。
//
// ライブラリ: bitcraze/Bitcraze_PMW3901（開発元Bitcraze公式、SPI・CSは任意のGPIOでよい）。
// begin()内部は`SPI.begin()`を引数無しで呼ぶだけだが、ESP32のSPIClass::begin()は
// 既にバスが開始済みなら何もせず戻る実装なので、下記のように先にカスタムピンで
// SPI.begin()しておけばそちらが優先される。
//
// 配線:
//   無印ESP32 DevKit(既定VSPIピン): VCC -> 3.3V, GND -> GND,
//     MOSI -> GPIO23, MISO -> GPIO19, SCK -> GPIO18, CS -> GPIO5
//     （TTGO T-Display等TFT搭載機で試すならfirmware/README.md「配線」の
//     空きピン表に従って読み替えること）
//   ESP32-C3 SuperMini: SCK -> GPIO4, MISO -> GPIO5, MOSI -> GPIO6, CS -> GPIO7
//     （docs/piezo.md §4のピン配置表のうち、GPIO2/GPIO9(ストラップ・BOOT)を
//     避けた空きピン。PMW3360DMのブリングアップと同じ配線を使い回せる）
#include <Arduino.h>
#include <Bitcraze_PMW3901.h>
#include <SPI.h>

namespace {
#ifdef CONFIG_IDF_TARGET_ESP32C3
constexpr int kSckPin = 4;
constexpr int kMisoPin = 5;
constexpr int kMosiPin = 6;
constexpr int kCsPin = 7;
#else
constexpr int kCsPin = 5;
#endif
Bitcraze_PMW3901 sensor(kCsPin);
constexpr uint32_t kSampleIntervalMs = 10;  // ドローン用途の既定フレームレートに合わせた目安
}  // namespace

void setup() {
  Serial.begin(115200);
#ifdef CONFIG_IDF_TARGET_ESP32C3
  SPI.begin(kSckPin, kMisoPin, kMosiPin, kCsPin);
#endif
  if (!sensor.begin()) {
    Serial.println("# PMW3901 init failed");
  } else {
    Serial.println("# PMW3901 init ok");
  }
  Serial.println("# t_ms,dx,dy");
}

void loop() {
  static uint32_t next_ms = millis();
  uint32_t now = millis();
  if (static_cast<int32_t>(now - next_ms) < 0) return;
  next_ms += kSampleIntervalMs;

  int16_t dx = 0, dy = 0;
  sensor.readMotionCount(&dx, &dy);
  Serial.printf("%lu,%d,%d\n", static_cast<unsigned long>(now), dx, dy);
}
