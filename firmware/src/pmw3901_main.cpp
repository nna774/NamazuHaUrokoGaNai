// PMW3901(オプティカルフローセンサ、ドローン用) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2「質量-バネ系+オプティカルフローピックアップ」phase0。
// 錘に取り付けてフレーム固定面を見て初めて意味を持つ方式（フレーム側に固定して
// 床や壁を見る使い方は不可、という同§3.1の注意を忘れずに——机上確認の段階では
// とりあえず手近な模様の上で動かして反応するかだけ見ればよい）。
// WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他。使い方は
// firmware/README.md参照）。
//
// ライブラリ: bitcraze/Bitcraze_PMW3901（開発元Bitcraze公式、SPI・CSは任意のGPIOでよい）。
//
// 配線（無印ESP32 DevKitでの既定VSPIピン。TTGO T-Display等TFT搭載機で試すなら
// firmware/README.md「配線」の空きピン表に従って読み替えること）:
//   VCC -> 3.3V, GND -> GND, MOSI -> GPIO23, MISO -> GPIO19, SCK -> GPIO18, CS -> GPIO5
#include <Arduino.h>
#include <Bitcraze_PMW3901.h>

namespace {
constexpr int kCsPin = 5;
Bitcraze_PMW3901 sensor(kCsPin);
constexpr uint32_t kSampleIntervalMs = 10;  // ドローン用途の既定フレームレートに合わせた目安
}  // namespace

void setup() {
  Serial.begin(115200);
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
