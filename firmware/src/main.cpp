// NamazuHaUrokoGaNai ファームウェア本体。
//
// Core1: 測定タスク（100Hzサンプリング + リアルタイム震度 + 検知）
// Core0: 送信タスク（バッチPOST / NTP / リトライ・バックフィル / WiFi再接続）
//
// NAMZ_SENSOR_TEST を定義してビルドすると WiFi/送信を行わず
// シリアルに "t_us,x,y,z" を出すだけ（tools/capture_serial.py 用・Phase1）。

#include <Arduino.h>
#include <SPI.h>
#include <WiFi.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>

#include "Batch.h"
#include "Iis3dhhc.h"
#include "Shindo.h"
#include "TimeSync.h"
#include "Uploader.h"
#include "config.h"

static SPIClass gSpi(VSPI);
static Iis3dhhc gSensor(gSpi, kPinCsIis3dhhc, kSpiClockHz);
static Shindo gShindo;

#ifndef NAMZ_SENSOR_TEST
static Uploader gUploader(kIngestUrl, kAlertUrl, kHmacSecret, kDeviceId,
                          kMaxRamBatches, kSpillDir);

struct AlertMsg {
  uint64_t us;
  float intensity;
  float peak;
};

static QueueHandle_t gBatchQueue;  // Batch*
static QueueHandle_t gAlertQueue;  // AlertMsg
#endif

static TaskHandle_t gSamplingTask;
static esp_timer_handle_t gSampleTimer;

// --- 100Hz タイマー: 測定タスクを起こす ---
static void IRAM_ATTR onSampleTimer(void*) {
  vTaskNotifyGiveFromISR(gSamplingTask, nullptr);
}

// --- 測定タスク（Core1）---
static void samplingTask(void*) {
  esp_task_wdt_add(nullptr);

  Batch* cur = nullptr;
  int sinceIntensity = 0;
  float holdSeconds = 0.0f;
  float cooldown = 0.0f;

  for (;;) {
    // タイマー通知待ち（1サンプル）
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    esp_task_wdt_reset();

    AccelSample raw;
    if (!gSensor.read(raw)) continue;
    uint64_t ts = timesync::nowUs();

#ifdef NAMZ_SENSOR_TEST
    // Phase1: 生LSBをそのまま出す
    Serial.printf("%llu,%d,%d,%d\n", (unsigned long long)ts,
                  (int)raw.x, (int)raw.y, (int)raw.z);
    continue;
#else
    // --- バッチ蓄積 ---
    if (cur == nullptr) {
      cur = new Batch(kBatchSamples);
      if (!cur->valid()) {  // メモリ不足: 次サンプルで再挑戦
        delete cur;
        cur = nullptr;
      } else {
        cur->begin(ts, gSensor.sensorType(), gSensor.sampleFormat(),
                   gSensor.scaleMgPerLsb(), kSampleRateHz, kDeviceId);
      }
    }
    if (cur) {
      cur->addSample((int16_t)raw.x, (int16_t)raw.y, (int16_t)raw.z);
      if (cur->isFull()) {
        if (xQueueSend(gBatchQueue, &cur, 0) != pdTRUE) {
          // 送信タスクが詰まっている: uploaderに直接渡す代わりに破棄回避のため待たない。
          // batchQueueは十分な深さを持たせている前提。溢れたら最古を諦める。
          Batch* dropped = nullptr;
          if (xQueueReceive(gBatchQueue, &dropped, 0) == pdTRUE) delete dropped;
          xQueueSend(gBatchQueue, &cur, 0);
        }
        cur = nullptr;
      }
    }

    // --- リアルタイム震度 & 検知 ---
    float gx = lsbToGal(raw.x, gSensor.scaleMgPerLsb());
    float gy = lsbToGal(raw.y, gSensor.scaleMgPerLsb());
    float gz = lsbToGal(raw.z, gSensor.scaleMgPerLsb());
    gShindo.push(gx, gy, gz);

    const float dt = 1.0f / kSampleRateHz;
    if (cooldown > 0) cooldown -= dt;

    if (++sinceIntensity >= kSampleRateHz / 4) {  // 0.25秒ごと
      sinceIntensity = 0;
      float intensity = gShindo.currentIntensity();
      if (intensity >= kAlertIntensity) {
        holdSeconds += 0.25f;
        if (holdSeconds >= kAlertHoldSeconds && cooldown <= 0) {
          AlertMsg m{ts, intensity, gShindo.lastComposite()};
          xQueueSend(gAlertQueue, &m, 0);
          cooldown = kAlertCooldownSeconds;
        }
      } else {
        holdSeconds = 0.0f;
      }
    }
#endif
  }
}

#ifndef NAMZ_SENSOR_TEST
static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(kWifiSsid, kWifiPass);
  Serial.print("[wifi] connecting");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(250);
    Serial.print('.');
  }
  Serial.printf("\n[wifi] %s\n",
                WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "FAILED");
}

// --- 送信タスク（Core0）---
static void uploaderTask(void*) {
  esp_task_wdt_add(nullptr);
  uint32_t lastResync = 0;

  for (;;) {
    esp_task_wdt_reset();

    // WiFi再接続
    if (WiFi.status() != WL_CONNECTED) {
      connectWifi();
    }
    // NTP再同期（間接: SNTPが自動pollするので明示不要だが接続回復時に備え）
    if (millis() - lastResync > kNtpResyncSeconds * 1000UL) {
      lastResync = millis();
    }

    // batchQueue -> uploader
    Batch* b = nullptr;
    while (xQueueReceive(gBatchQueue, &b, 0) == pdTRUE) {
      gUploader.enqueue(b);
    }
    // alertQueue -> 即時送信
    AlertMsg m;
    while (xQueueReceive(gAlertQueue, &m, 0) == pdTRUE) {
      bool ok = gUploader.sendAlert(m.us, m.intensity, m.peak);
      Serial.printf("[alert] I=%.1f peak=%.2fgal sent=%d\n", m.intensity, m.peak, ok);
    }

    gUploader.pump();
    delay(50);
  }
}
#endif

void setup() {
  Serial.begin(921600);
  delay(200);
  Serial.println("\n[boot] NamazuHaUrokoGaNai");

  gSpi.begin(kPinSck, kPinMiso, kPinMosi, kPinCsIis3dhhc);
  if (!gSensor.begin()) {
    Serial.println("[sensor] IIS3DHHC not found! (WHO_AM_I mismatch)");
  } else {
    Serial.println("[sensor] IIS3DHHC ready");
  }

  // watchdog: 10秒
  esp_task_wdt_config_t wdt = {.timeout_ms = 10000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wdt);

#ifndef NAMZ_SENSOR_TEST
  gBatchQueue = xQueueCreate(4, sizeof(Batch*));
  gAlertQueue = xQueueCreate(4, sizeof(AlertMsg));
  connectWifi();
  timesync::begin(kNtpServer1, kNtpServer2);
  gUploader.begin();
  xTaskCreatePinnedToCore(uploaderTask, "uploader", 12288, nullptr, 1, nullptr, 0);
#endif

  // 測定タスクは Core1 に高優先度で固定
  xTaskCreatePinnedToCore(samplingTask, "sampling", 8192, nullptr, 10, &gSamplingTask, 1);

  // 100Hz タイマー
  const esp_timer_create_args_t targs = {
      .callback = &onSampleTimer, .arg = nullptr,
      .dispatch_method = ESP_TIMER_TASK, .name = "sample", .skip_unhandled_events = true};
  esp_timer_create(&targs, &gSampleTimer);
  esp_timer_start_periodic(gSampleTimer, kSamplePeriodUs);
}

void loop() {
  // 全処理はタスク側。loopは何もしない。
  vTaskDelay(pdMS_TO_TICKS(1000));
}
