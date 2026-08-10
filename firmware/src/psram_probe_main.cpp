// PSRAM(外付けSPI RAM)搭載機かどうかを実機で確かめるだけの使い捨てビルド。
// docs/log/2026-08-10-newbatch-buffer-pool-handoff.md 参照——newBatch()の
// バッファプールをDRAMではなくPSRAMに置けないか検討するための事前確認。
//
// esp32dev boardのSDK(qio_qspi等)はCONFIG_SPIRAM=1で常にビルドされている
// （tools/sdk/esp32/qio_qspi/include/sdkconfig.h参照。CONFIG_SPIRAM_BOOT_INIT
// も未定義なので、psramInit()はスタブではなく実際にSPIでPSRAMへ話しかけて
// 検出する実装が動く）。既存envの追加ボード設定は不要で、このまま焼ける。
//
//   pio run -e psram-probe -t upload --upload-port <USBポート>
//   pio device monitor
#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[psram-probe] booting...");
  bool initOk = psramInit();
  Serial.printf("[psram-probe] psramInit() -> %d\n", (int)initOk);
  Serial.printf("[psram-probe] psramFound() -> %d\n", (int)psramFound());
  Serial.printf("[psram-probe] ESP.getPsramSize() -> %u bytes\n",
                (unsigned)ESP.getPsramSize());
  Serial.printf("[psram-probe] ESP.getFreePsram() -> %u bytes\n",
                (unsigned)ESP.getFreePsram());
  Serial.println("[psram-probe] done. size==0 means PSRAM not found / not wired.");
}

void loop() {
  delay(5000);
  Serial.println("[psram-probe] still alive");
}
