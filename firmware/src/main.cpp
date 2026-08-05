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
#include <time.h>

#include "Batch.h"
#include "Display.h"
#include "NamzWire.h"
#ifdef NAMZ_SENSOR_ADXL355
#include "Adxl355.h"
#else
#include "Iis3dhhc.h"
#endif
#include "Shindo.h"
#include "TimeSync.h"
#include "Uploader.h"
#include "config.h"

static SPIClass gSpi(VSPI);
// センサはビルド時に選ぶ（-DNAMZ_SENSOR_ADXL355）。CSが別ピンなので、比較のため
// 両方を同じバスにぶら下げたままファームだけ焼き分けてもよい。
#ifdef NAMZ_SENSOR_ADXL355
static constexpr int kPinCsSensor = kPinCsAdxl355;
static constexpr const char* kSensorName = "ADXL355";
static Adxl355 gSensor(gSpi, kPinCsSensor, kSpiClockHz);
#else
static constexpr int kPinCsSensor = kPinCsIis3dhhc;
static constexpr const char* kSensorName = "IIS3DHHC";
static Iis3dhhc gSensor(gSpi, kPinCsSensor, kSpiClockHz);
#endif
static Shindo gShindo;
static Display gDisplay;

// 表示用の共有状態（測定タスクが書き、loopが読む）。
static volatile float gDispIntensity = 0.0f;
static volatile float gDispPeakGal = 0.0f;
static volatile uint32_t gLastShakeMs = 0;  // 瞬時合成加速度がしきい値を超えた最終時刻

#ifndef NAMZ_SENSOR_TEST
// spillも満杯なら最古のバッチから捨てる（無制限にRAMへ積み増してクラッシュするのを防ぐ）。
static Uploader gUploader(kIngestUrl, kAlertUrl, kHmacSecret, kDeviceId,
                          kMaxRamBatches, kSpillDir, /*dropOldestWhenFull=*/true);

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

  // オーバーサンプリング用アキュムレータ
  int32_t accX = 0, accY = 0, accZ = 0;
  int oversampleCount = 0;

  for (;;) {
    // タイマー通知待ち（読み周期 = 出力周期/kOversample）
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    esp_task_wdt_reset();

    AccelSample rd;
    if (!gSensor.read(rd)) continue;
    accX += rd.x;
    accY += rd.y;
    accZ += rd.z;
    if (++oversampleCount < (int)kOversample) continue;  // まだ蓄積中

    // kOversample 個たまった → 平均して1サンプル(100Hz)を出力
    AccelSample raw{accX / (int32_t)kOversample,
                    accY / (int32_t)kOversample,
                    accZ / (int32_t)kOversample};
    accX = accY = accZ = 0;
    oversampleCount = 0;
    uint64_t ts = timesync::nowUs();

#ifdef NAMZ_SENSOR_TEST
    // Phase1: 平均後の100Hzサンプル(LSB)を出す
    Serial.printf("%llu,%d,%d,%d\n", (unsigned long long)ts,
                  (int)raw.x, (int)raw.y, (int)raw.z);
    continue;
#else
    // NTP同期前はタイムスタンプが無効(1970年)になるのでサンプルを捨てる。
    // 起動直後の数秒ぶんを失うだけで、24/365運用では無視できる。
    if (!timesync::isSynced()) continue;

    // --- バッチ蓄積 ---
    if (cur == nullptr) {
      cur = namzwire::newBatch(kBatchSamples, gSensor.sampleFormat());
      if (!cur->valid()) {  // メモリ不足: 次サンプルで再挑戦
        delete cur;
        cur = nullptr;
      } else {
        cur->begin(ts);
        // 温度はバッチ先頭の1点だけ載せる。架台の熱ドリフトは分〜時間の時定数で
        // 動くので、30秒に1点あれば傾きは追える。
        uint16_t temp = 0;
        if (gSensor.readTemperatureRaw(temp)) {
          namzwire::addTrailer(*cur, kTrailerSensorTemp, &temp, sizeof(temp));
        }
      }
    }
    if (cur) {
      namzwire::addSample(*cur, raw.x, raw.y, raw.z);
      if (cur->isFull()) {
        // ヘッダはここで書く。sample_count が確定するのが「積み終えた後」だから。
        // Batch はワイヤ形式を知らないので、この一手だけがNAMZ形式を作っている。
        namzwire::fillHeader(*cur, gSensor.sensorType(), gSensor.scaleMgPerLsb(),
                             kSampleRateHz, kDeviceId);
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
    float comp = gShindo.push(gx, gy, gz);

    // 瞬時の揺れ判定と表示用ピーク（減衰エンベロープ）
    if (comp >= kDispActiveGal) gLastShakeMs = millis();
    gDispPeakGal = comp > gDispPeakGal ? comp : gDispPeakGal * 0.99f;

    const float dt = 1.0f / kSampleRateHz;
    if (cooldown > 0) cooldown -= dt;

    if (++sinceIntensity >= kSampleRateHz / 4) {  // 0.25秒ごと
      sinceIntensity = 0;
      float intensity = gShindo.currentIntensity();
      gDispIntensity = intensity;  // 表示用に共有
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
    // 最大20秒ブロックするので、ウォッチドッグ(10秒)に登録済みのタスクから
    // 呼ばれると待っているだけで panic する。未登録タスクから呼ばれた場合は
    // ESP_ERR_NOT_FOUND が返るだけで無害。
    esp_task_wdt_reset();
    Serial.print('.');
  }
  Serial.printf("\n[wifi] %s\n",
                WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "FAILED");
}

// --- 送信タスク（Core0）---
static void uploaderTask(void*) {
  esp_task_wdt_add(nullptr);
  uint32_t lastResync = 0;

  // このタスクは1周の中でネットワーク待ちを何度もする。TLS接続のタイムアウトは
  // 1回あたり5秒あり、回線が詰まると「速報送信で5秒＋バッチ送信で5秒」で簡単に
  // ウォッチドッグの10秒を超える（実機で panic 再起動した）。タスクはハングして
  // おらず、ソケットを待っているだけなので、ブロックしうる呼び出しの前後で
  // 明示的に餌をやる。ここを削ると回線が詰まった時に限って再起動する。
  for (;;) {
    esp_task_wdt_reset();

    // WiFi再接続
    if (WiFi.status() != WL_CONNECTED) {
      connectWifi();
      esp_task_wdt_reset();
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
      // 速報の本文は地震計固有なのでここで組む（Uploader は運びかたしか知らない）。
      char json[256];
      int n = snprintf(json, sizeof(json),
                       "{\"device_id\":%u,\"detected_at_us\":%llu,"
                       "\"realtime_intensity\":%.2f,\"peak_gal\":%.3f,"
                       "\"kind\":\"device_prompt\"}",
                       (unsigned)kDeviceId, (unsigned long long)m.us,
                       m.intensity, m.peak);
      bool ok = gUploader.sendAlert(json, n);
      esp_task_wdt_reset();
      Serial.printf("[alert] I=%.1f peak=%.2fgal sent=%d\n", m.intensity, m.peak, ok);
    }

    gUploader.pump();
    esp_task_wdt_reset();
    delay(50);
  }
}
#endif

void setup() {
  Serial.begin(kSerialBaud);
  delay(200);
  Serial.println("\n[boot] NamazuHaUrokoGaNai");

  gDisplay.begin(kDeviceId);
  pinMode(kPinButtonFlip, INPUT_PULLUP);

  gSpi.begin(kPinSck, kPinMiso, kPinMosi, kPinCsSensor);
  if (!gSensor.begin()) {
    Serial.printf("[sensor] %s not found! (ID mismatch)\n", kSensorName);
  } else {
    Serial.printf("[sensor] %s ready\n", kSensorName);
  }

  // watchdog: 10秒。WDT APIは ESP-IDF のメジャーバージョンで異なる。
#if ESP_IDF_VERSION_MAJOR >= 5
  esp_task_wdt_config_t wdt = {.timeout_ms = 10000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wdt);
#else
  esp_task_wdt_init(10, true);  // 旧API: timeout[秒], panic
#endif

#ifndef NAMZ_SENSOR_TEST
  gBatchQueue = xQueueCreate(4, sizeof(Batch*));
  gAlertQueue = xQueueCreate(4, sizeof(AlertMsg));
  connectWifi();
  timesync::begin(kNtpServer1, kNtpServer2,
                  static_cast<uint64_t>(kNtpStepThresholdSeconds) * 1000000ULL);
  gUploader.begin();
  xTaskCreatePinnedToCore(uploaderTask, "uploader", 12288, nullptr, 1, nullptr, 0);
#endif

  // バッチ1本のRAM量はセンサのサンプル幅で倍違う（int16 18KB / int32 36KB）。
  // kMaxRamBatches が実機のヒープに収まっているかを起動時に見えるようにしておく。
  Serial.printf("[mem] free heap %u maxblock %u, batch %u B x %u\n",
                ESP.getFreeHeap(), ESP.getMaxAllocHeap(),
                (unsigned)(kBatchSamples * (gSensor.sampleFormat() == 1 ? 12 : 6)),
                (unsigned)kMaxRamBatches);

  // 測定タスクは Core1 に高優先度で固定
  xTaskCreatePinnedToCore(samplingTask, "sampling", 8192, nullptr, 10, &gSamplingTask, 1);

  // 読み取りタイマー（1kHz = 出力100Hz × オーバーサンプル10）
  const esp_timer_create_args_t targs = {
      .callback = &onSampleTimer, .arg = nullptr,
      .dispatch_method = ESP_TIMER_TASK, .name = "sample", .skip_unhandled_events = true};
  esp_timer_create(&targs, &gSampleTimer);
  esp_timer_start_periodic(gSampleTimer, kReadPeriodUs);
}

void loop() {
  // 測定/送信はタスク側。loopはボタンとTFT表示だけ担う。
  static bool prevPressed = false;
  static uint32_t sessStart = 0;
  static bool active = false;
  static int tick = 0;

  // ボタン押下エッジで画面反転
  bool pressed = digitalRead(kPinButtonFlip) == LOW;
  if (pressed && !prevPressed) gDisplay.toggleFlip();
  prevPressed = pressed;

  // 継続ステートの算出（瞬時の揺れベース）
  uint32_t now = millis();
  uint32_t sinceShake = now - gLastShakeMs;  // 最後に瞬時しきい値を超えてからの経過[ms]
  bool shakingNow = sinceShake < kShakeHangoverMs;
  if (shakingNow && !active) { active = true; sessStart = now; }
  if (active && sinceShake > kDispCloseSeconds * 1000UL) active = false;

  // 継続ステートを画面全体の背景色で表す（遠目でも判別できるように）。
  // idle=暗い紺 / closing=橙 / active=赤。文字色はDisplay側で背景から自動選択。
  String status;
  uint16_t bg;
  if (active && shakingNow) {
    status = "ACTIVE " + String((now - sessStart) / 1000) + "s";
    bg = TFT_RED;
  } else if (active) {
    uint32_t elapsed = sinceShake / 1000;
    uint32_t left = elapsed >= kDispCloseSeconds ? 0 : kDispCloseSeconds - elapsed;
    status = "closing " + String(left) + "s";
    bg = TFT_ORANGE;
  } else {
    status = "idle";
    bg = TFT_NAVY;
  }

  // 描画は約500msごと（ボタンは250msごとに見る）
  if (++tick % 2 == 0) {
    // 日時（表示用にJST=UTC+9h。データ経路はUTCのまま触らない）。
    String clock;
    if (timesync::isSynced()) {
      time_t t = (time_t)(timesync::nowUs() / 1000000ULL) + 9 * 3600;
      struct tm tmv;
      gmtime_r(&t, &tmv);
      char cb[20];
      snprintf(cb, sizeof(cb), "%02d/%02d %02d:%02d:%02d", tmv.tm_mon + 1,
               tmv.tm_mday, tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
      clock = cb;
    } else {
      clock = "--/-- --:--:--";
    }
#ifdef NAMZ_SENSOR_TEST
    gDisplay.render(gDispIntensity, gDispPeakGal, false, "", 0, 0, status, bg, clock);
#else
    bool wifi = WiFi.status() == WL_CONNECTED;
    String ip = wifi ? WiFi.localIP().toString() : String("");
    uint32_t backlog = gUploader.spillCount() + gUploader.ramQueued();
    uint32_t backlogAgeS = 0;
    uint64_t oldestUs;
    if (backlog > 0 && timesync::isSynced() &&
        gUploader.oldestQueuedStartUs(oldestUs)) {
      uint64_t nowUs = timesync::nowUs();
      backlogAgeS = nowUs > oldestUs ? (uint32_t)((nowUs - oldestUs) / 1000000ULL) : 0;
    }
    gDisplay.render(gDispIntensity, gDispPeakGal, wifi, ip, backlog, backlogAgeS,
                    status, bg, clock);
#endif
  }
  vTaskDelay(pdMS_TO_TICKS(250));
}
