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
//     3.3V/GND側の辺に寄せたい時は[env:mlx90393-bringup-c3-gpio34]: SDA -> GPIO3, SCL -> GPIO4
//     （GPIO0〜4はこの辺。GPIO2はストラップなので避ける。図解のSDA/SCLをGPIO3/4へ読み替える）
//     図解: docs/img/mlx90393-esp32c3-wiring.svg（SS49Eと同じ実機、2026-08-27に
//     写真で確認済みの実物ピン配置。SDA/SCLは基板の反対側の辺にあるため配線が
//     長くなる点に注意）
//
// GY-MLX90393等のSPI/I2C両対応ブレークアウトを使う場合の注意: チップは電源投入時の
// CS状態でI2C/SPIを自動判定するため、**CSを3.3Vへ固定してI2Cモードを強制すること**
// （浮かせるとI2Cで安定動作しない恐れがある）。MISO/MOSI/SCLK/TRIG/INT/A0/A1は未使用。
#include <Arduino.h>
#include <MLX90393.h>
#include <Wire.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

namespace {
MLX90393 sensor;
constexpr uint32_t kSampleIntervalMs = 20;  // ~50Hz。OSR/DIGFILT既定値での実効変換時間に合わせて後で調整
// ピン番号はビルドフラグ -DMLX90393_SDA_PIN=n -DMLX90393_SCL_PIN=n で上書きできる
// （C3 SuperMiniで3.3V/GND側の辺にあるGPIO3/4へ寄せる[env:mlx90393-bringup-c3-gpio34]用）。
#ifndef MLX90393_SDA_PIN
#ifdef CONFIG_IDF_TARGET_ESP32C3
#define MLX90393_SDA_PIN 5
#define MLX90393_SCL_PIN 6
#else
#define MLX90393_SDA_PIN 21
#define MLX90393_SCL_PIN 22
#endif
#endif
constexpr int kSdaPin = MLX90393_SDA_PIN;
constexpr int kSclPin = MLX90393_SCL_PIN;
}  // namespace

void setup() {
  Serial.begin(115200);
  Wire.begin(kSdaPin, kSclPin);
  uint8_t status = sensor.begin(0, 0, -1, Wire);  // A1=0, A0=0（既定アドレス）, DRDYピン未使用
  Serial.printf("# begin status=0x%02x reset_reason=%d\n", status, static_cast<int>(esp_reset_reason()));
  // 長時間の取り込みで、ループがSerial出力かI2Cの待ちから戻れず無出力になったことがある
  // (2026-10-29、Saved PC=esp_cpu_wait_for_intr=割り込み待ちのまま)。無出力のまま固まらないよう
  // タスクWDT(30秒)で再起動させる。reset_reason(=ESP_RST_TASK_WDT 7等)を起動時に出して後から分かるようにする。
  esp_task_wdt_config_t wdt = {.timeout_ms = 30000, .idle_core_mask = 0, .trigger_panic = true};
  if (esp_task_wdt_reconfigure(&wdt) != ESP_OK) esp_task_wdt_init(&wdt);
  esp_task_wdt_add(nullptr);
  Serial.println("# t_ms,status,x_uT,y_uT,z_uT,temp_C");
}

void loop() {
  esp_task_wdt_reset();
  static uint32_t next_ms = millis();
  uint32_t now = millis();
  if (static_cast<int32_t>(now - next_ms) < 0) return;
  next_ms += kSampleIntervalMs;

  MLX90393::txyz data;
  uint8_t status = sensor.readData(data);
  Serial.printf("%lu,0x%02x,%.2f,%.2f,%.2f,%.2f\n", static_cast<unsigned long>(now), status,
                data.x, data.y, data.z, data.t);
}
