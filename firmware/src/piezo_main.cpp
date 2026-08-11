// ピエゾ実験機(ESP32-C3スーパーミニ)のエントリポイント。
//
// 本線main.cppとは別ファイル（provision_main.cpp等と同じパターン、
// platformio.iniのbuild_src_filterでmain.cppと排他）。ESP32-C3はシングルコア
// なので、測定タスク・送信タスクは同一コア上のFreeRTOSタスクとして分離する
// (docs/design.md「ESP32ボードの差し替え」、docs/piezo.md §7)。
// 将来デュアルコア機に載せる場合はxTaskCreateをxTaskCreatePinnedToCoreに
// 変えてコアを指定するだけで済むよう、キュー経由の連携にしてある。
//
// 校正しない・タイミング一致だけを狙う非校正センサ(docs/other-sensors.md)なので、
// 本線のリアルタイム震度計算(Shindo)・device_promptアラート・TFT表示・OTAは
// 持たない。OTAは後で足しやすいよう、送信タスクにチェック呼び出しの余地は
// 空けてあるが今回は実装しない(docs/piezo.md §7)。

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>

#include "Batch.h"
#include "DeviceIdentity.h"
#include "NamzWire.h"
#include "PiezoSensor.h"
#include "TimeSync.h"
#include "TlsMemPool.h"
#include "Uploader.h"
#include "piezo_config.h"

// firmware/certs/amazon_root_ca1.pem を platformio.ini の board_build.embed_txtfiles
// でリンクする（本線main.cppと同じ手法）。
extern const uint8_t amazon_root_ca1_pem_start[] asm("_binary_certs_amazon_root_ca1_pem_start");

static PiezoSensor gSensor(kPiezoPin, kSensorTypePiezo);
static DeviceIdentity gIdentity;
static Uploader* gUploader = nullptr;
static QueueHandle_t gBatchQueue;
static TaskHandle_t gSamplingTask;
static esp_timer_handle_t gSampleTimer;

static void IRAM_ATTR onSampleTimer(void*) {
  vTaskNotifyGiveFromISR(gSamplingTask, nullptr);
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(gIdentity.wifiSsid.c_str(), gIdentity.wifiPass.c_str());
  Serial.print("[wifi] connecting");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(250);
    esp_task_wdt_reset();
    Serial.print('.');
  }
  Serial.printf("\n[wifi] %s\n",
                WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "FAILED");
}

// --- 測定タスク ---
// 本線と違いオーバーサンプリング・リアルタイム震度計算(Shindo)は持たない。
// 読んで貯めて満杯になったら送信キューへ渡すだけ。
static void samplingTask(void*) {
  esp_task_wdt_add(nullptr);
  Batch* cur = nullptr;

  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    esp_task_wdt_reset();

    int32_t raw[1];
    if (!gSensor.read(raw)) continue;
    uint64_t ts = timesync::nowUs();
    // NTP同期前はタイムスタンプが無効(1970年)になるので捨てる(本線と同じ方針)。
    if (!timesync::isSynced()) continue;

    if (cur == nullptr) {
      cur = namzwire::newBatch(kBatchSamples, gSensor.sampleFormat(), gSensor.axes());
      if (!cur || !cur->valid()) {
        delete cur;
        cur = nullptr;
        continue;  // メモリ不足: 次サンプルで再挑戦(本線と同じ経路)
      }
      cur->begin(ts);
    }
    namzwire::addSampleN(*cur, raw, gSensor.axes());
    if (cur->isFull()) {
      // scaleMgPerLsbは非校正センサでは意味を持たない(docs/wire_format.md
      // 「sensor_type の帯域」)ので1.0を入れる。
      namzwire::fillHeader(*cur, gSensor.sensorType(), /*scaleMgPerLsb=*/1.0f,
                           kSampleRateHz, gIdentity.deviceId, gSensor.axes());
      if (xQueueSend(gBatchQueue, &cur, 0) != pdTRUE) {
        Serial.println("[sampling] gBatchQueue full, dropping oldest queued batch");
        Batch* dropped = nullptr;
        if (xQueueReceive(gBatchQueue, &dropped, 0) == pdTRUE) delete dropped;
        xQueueSend(gBatchQueue, &cur, 0);
      }
      cur = nullptr;
    }
  }
}

// --- 送信タスク ---
// 本線は「吸い出し」「送信」を2タスクに分けている(LittleFS競合回避、
// docs/log/2026-08-11-uploader-task-split.md)が、ここではまず1タスクに
// まとめる。詰まりが実機で見えたら分割を検討する。
static void uploaderTask(void*) {
  for (;;) {
    Batch* b = nullptr;
    while (xQueueReceive(gBatchQueue, &b, 0) == pdTRUE) {
      gUploader->enqueue(b);
    }
    gUploader->pump();
    // TODO(OTA): ここにpull型OTAのチェック呼び出しを足せる(docs/piezo.md §7、
    // 今回は未実装)。
    delay(50);
  }
}

void setup() {
  Serial.begin(kSerialBaud);
  delay(200);
  Serial.printf("\n[boot] NamazuHaUrokoGaNai piezo fw=%s\n", kFwVersion);

  // WiFi/Uploaderより前、mbedTLSが一度も呼ばれていないうちにフックする
  // (本線main.cppと同じ理由)。
  tlsmempool::install();

  loadDeviceIdentity(gIdentity);
  if (!gSensor.begin()) {
    Serial.println("[sensor] piezo init failed");
  }

#if ESP_IDF_VERSION_MAJOR >= 5
  esp_task_wdt_config_t wdt = {.timeout_ms = 20000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wdt);
#else
  esp_task_wdt_init(20, true);
#endif

  if (gIdentity.deviceId == 0 || gIdentity.wifiSsid.length() == 0 ||
      gIdentity.hmacSecret.length() == 0 || gIdentity.ingestUrl.length() == 0) {
    for (;;) {
      Serial.println("[boot] device identity not provisioned in NVS. halting.");
      delay(5000);
    }
  }

  gBatchQueue = xQueueCreate(4, sizeof(Batch*));
  connectWifi();
  timesync::begin(kNtpServer1, kNtpServer2,
                  static_cast<uint64_t>(kNtpStepThresholdSeconds) * 1000000ULL);

  gUploader = new Uploader(gIdentity.ingestUrl.c_str(), gIdentity.alertUrl.c_str(),
                           gIdentity.hmacSecret.c_str(), gIdentity.deviceId,
                           kMaxRamBatches, kSpillDir, /*dropOldestWhenFull=*/true,
                           /*watchResponseHeaders=*/nullptr,
                           /*extraRequestHeaderNames=*/nullptr,
                           /*extraRequestHeaderValues=*/nullptr,
                           reinterpret_cast<const char*>(amazon_root_ca1_pem_start));
  gUploader->begin();

  if (xTaskCreate(uploaderTask, "uploader", 8192, nullptr, 1, nullptr) != pdPASS) {
    for (;;) {
      Serial.println("[boot] BUG: uploaderTask creation failed (heap exhausted?). halting.");
      delay(5000);
    }
  }

  Serial.printf("[mem] free heap %u maxblock %u, batch %u B x %u\n",
                ESP.getFreeHeap(), ESP.getMaxAllocHeap(),
                (unsigned)(kBatchSamples * 2), (unsigned)kMaxRamBatches);

  if (xTaskCreate(samplingTask, "sampling", 4096, nullptr, 10, &gSamplingTask) != pdPASS) {
    for (;;) {
      Serial.println("[boot] BUG: samplingTask creation failed (heap exhausted?). halting.");
      delay(5000);
    }
  }

  const esp_timer_create_args_t targs = {
      .callback = &onSampleTimer, .arg = nullptr,
      .dispatch_method = ESP_TIMER_TASK, .name = "sample", .skip_unhandled_events = true};
  esp_timer_create(&targs, &gSampleTimer);
  esp_timer_start_periodic(gSampleTimer, kSamplePeriodUs);
}

void loop() {
  esp_task_wdt_reset();
  delay(1000);
}
