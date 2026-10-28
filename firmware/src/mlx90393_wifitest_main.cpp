// MLX90393へのWiFi電流の影響を測る使い捨てスケッチ（tools/mag_wifi_effect.pyで解析する）。
// 方位センサを本線のESP32と同居させる前に、WiFiを動かすとセンサの出力が動くかを実測する目的
// （docs/log/2026-10-29-mag-check-tool.md）。mlx90393_main.cppとはsetup()/loop()が排他。
//
// 窓の切り替え（kWindowMs=20秒ごとに交互、先頭は静か）:
//   phase 0 = WiFi OFF（無線の電流なし）
//   phase 1 = WiFi STA + 非同期スキャンを連続実行（プローブ送信と受信待ちで送受信の電流が出る）
// 資格情報は要らない（接続はしない）。接続して実際にTLSで送る負荷は別途。
// スキャンは常時送受信しているわけではないので、本線の送信負荷の上限を見ているわけではない点に注意。
//
// 出力CSV: t_ms,status,x_uT,y_uT,z_uT,temp_C,phase
// ピン・配線はmlx90393_main.cppと同じ（-DMLX90393_SDA_PIN/-DMLX90393_SCL_PINで上書き可）。
#include <Arduino.h>
#include <MLX90393.h>
#include <WiFi.h>
#include <Wire.h>

namespace {
MLX90393 sensor;
constexpr uint32_t kWindowMs = 20000;
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
int gPhase = -1;

void enterPhase(int phase) {
  if (phase == 1) {
    WiFi.mode(WIFI_STA);
    WiFi.setTxPower(WIFI_POWER_19_5dBm);
  } else {
    WiFi.scanDelete();
    WiFi.mode(WIFI_OFF);
  }
  gPhase = phase;
}
}  // namespace

void setup() {
  Serial.begin(115200);
  Wire.begin(kSdaPin, kSclPin);
  uint8_t status = sensor.begin(0, 0, -1, Wire);
  Serial.printf("# begin status=0x%02x window=%lums\n", status, static_cast<unsigned long>(kWindowMs));
  Serial.println("# t_ms,status,x_uT,y_uT,z_uT,temp_C,phase");
  enterPhase(0);
}

void loop() {
  uint32_t now = millis();
  int want = (now / kWindowMs) % 2;
  if (want != gPhase) enterPhase(want);
  if (gPhase == 1 && WiFi.scanComplete() != WIFI_SCAN_RUNNING) {
    WiFi.scanDelete();
    WiFi.scanNetworks(true, true, false, 300);  // 非同期・隠しSSID含む・アクティブ
  }

  MLX90393::txyz data;
  uint8_t status = sensor.readData(data);
  Serial.printf("%lu,0x%02x,%.2f,%.2f,%.2f,%.2f,%d\n", static_cast<unsigned long>(now), status,
                data.x, data.y, data.z, data.t, gPhase);
}
