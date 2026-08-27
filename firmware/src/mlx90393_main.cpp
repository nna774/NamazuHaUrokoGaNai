// MLX90393(3軸I2Cデジタル磁気センサ) 机上確認用スケッチ。
// docs/other-sensors.md §3.1/3.2「質量-バネ系+磁気ピックアップ」phase0の高精度側。
// SS49Eで方向情報や精度が足りないと分かった時にこちらへ進む想定（同§3.2）。
// WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他。
// [env:mlx90393-bringup](無印ESP32)・[env:mlx90393-bringup-c3](ESP32-C3 SuperMini)。
// 使い方はfirmware/README.md参照）。
//
// ライブラリ: tedyapo/arduino-MLX90393（SparkFunのQwiic Hookup GuideもこれをExampleに
// 使っている、I2C版の定番実装）。タグが無いリポジトリなので上記envのlib_depsでは
// コミットハッシュでpinしてある。
//
// 配線（SparkFun Qwiicブレークアウトならアドレスジャンパ A0=A1=GND=デフォルト0,0の
// ままでよい）:
//   無印ESP32 DevKit: SDA -> GPIO21, SCL -> GPIO22 (ESP32既定のWireピン)
//   ESP32-C3 SuperMini: SDA -> GPIO5, SCL -> GPIO6（GPIO2/GPIO9(ストラップ・BOOT)を
//     避けた空きピン、チップ仕様なので基板差の影響を受けない）。
//     図解: docs/img/mlx90393-esp32c3-wiring.svg（SS49Eと同じ実機、2026-08-27に
//     写真で確認済みの実物ピン配置。SDA/SCLは基板の反対側の辺にあるため配線が
//     長くなる点に注意）
#include <Arduino.h>
#include <MLX90393.h>
#include <Wire.h>

namespace {
MLX90393 sensor;
constexpr uint32_t kSampleIntervalMs = 20;  // ~50Hz。OSR/DIGFILT既定値での実効変換時間に合わせて後で調整
#ifdef CONFIG_IDF_TARGET_ESP32C3
constexpr int kSdaPin = 5;
constexpr int kSclPin = 6;
#else
constexpr int kSdaPin = 21;
constexpr int kSclPin = 22;
#endif
}  // namespace

void setup() {
  Serial.begin(115200);
  Wire.begin(kSdaPin, kSclPin);
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
