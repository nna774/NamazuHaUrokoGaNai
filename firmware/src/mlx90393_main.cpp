// MLX90393(3軸I2Cデジタル磁気センサ) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2「質量-バネ系+磁気ピックアップ」phase0の高精度側。
// SS49Eで方向情報や精度が足りないと分かった時にこちらへ進む想定（同§3.2）。
// WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他。使い方は
// firmware/README.md参照）。
//
// ライブラリ: tedyapo/arduino-MLX90393（SparkFunのQwiic Hookup GuideもこれをExampleに
// 使っている、I2C版の定番実装）。タグが無いリポジトリなので[env:mlx90393-bringup]の
// lib_depsではコミットハッシュでpinしてある。
//
// 配線（無印ESP32 DevKitでの既定。SparkFun Qwiicブレークアウトならアドレスジャンパ
// A0=A1=GND=デフォルト0,0のままでよい）:
//   VCC -> 3.3V, GND -> GND, SDA -> GPIO21, SCL -> GPIO22 (ESP32既定のWireピン)
#include <Arduino.h>
#include <MLX90393.h>
#include <Wire.h>

namespace {
MLX90393 sensor;
constexpr uint32_t kSampleIntervalMs = 20;  // ~50Hz。OSR/DIGFILT既定値での実効変換時間に合わせて後で調整
}  // namespace

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  uint8_t status = sensor.begin(0, 0, -1, Wire);  // A1=0, A0=0（既定アドレス）, DRDYピン未使用
  Serial.printf("# begin status=0x%02x\n", status);
  Serial.println("# t_ms,status,x_uT,y_uT,z_uT,temp_C");
}

void loop() {
  static uint32_t next_ms = millis();
  uint32_t now = millis();
  if (static_cast<int32_t>(now - next_ms) < 0) return;
  next_ms += kSampleIntervalMs;

  MLX90393::txyz data;
  uint8_t status = sensor.readData(data);
  Serial.printf("%lu,0x%02x,%.2f,%.2f,%.2f,%.2f\n", static_cast<unsigned long>(now), status,
                data.x, data.y, data.z, data.t);
}
