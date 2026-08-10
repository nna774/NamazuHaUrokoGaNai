// NVS(Preferences)へデバイス識別情報・秘密・エンドポイントURLを書き込むだけの
// 専用ビルド（docs/ota.md §2）。通常のfirmware(main.cpp)とは排他で、
// platformio.iniの[env:provision]/[env:adxl355-provision]だけがこれをビルドする。
//
// 使い方:
//   python tools/provision_device.py provision-h --id N
//   pio run -e provision -t upload --upload-port <USBポート>   # これを焼いて1回起動
//   pio run -e esp32dev -t upload --upload-port <USBポート>    # 続けて通常のfirmwareを焼く

#include <Arduino.h>

#include "DeviceIdentity.h"
#include "secrets_provision.h"

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[provision] writing device identity to NVS...");

  DeviceIdentity id;
  id.deviceId = kProvDeviceId;
  id.wifiSsid = kProvWifiSsid;
  id.wifiPass = kProvWifiPass;
  id.hmacSecret = kProvHmacSecret;
  id.ingestUrl = kProvIngestUrl;
  id.alertUrl = kProvAlertUrl;
  id.apiUrl = kProvApiUrl;
  id.otaBaseUrl = kProvOtaBaseUrl;

  bool wrote = saveDeviceIdentity(id);

  DeviceIdentity readback;
  bool verified = wrote && loadDeviceIdentity(readback) && readback.deviceId == id.deviceId &&
                  readback.hmacSecret == id.hmacSecret;

  if (verified) {
    Serial.printf("[provision] OK: device %u written and verified.\n", (unsigned)id.deviceId);
    Serial.println("[provision] Now flash the normal firmware (pio run -e <env> -t upload).");
  } else {
    Serial.println("[provision] FAILED to write/verify NVS. Do not flash the normal firmware.");
  }
}

void loop() { delay(1000); }
