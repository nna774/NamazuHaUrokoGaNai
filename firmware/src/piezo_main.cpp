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
// 本線のリアルタイム震度計算(Shindo)・device_promptアラート・TFT表示は持たない。
// pull型OTA(docs/ota.md §2)は本線から移植した(docs/piezo.md §7)。TFT/OLED画面が
// 無いため「更新中」の視覚表示は無い。

#include <Arduino.h>
#include <HTTPUpdate.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_system.h>
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
// でリンクする（本線main.cppと同じ手法）。OTA取得先(CloudFront)とingest先の両方の
// TLS検証に使う。
extern const uint8_t amazon_root_ca1_pem_start[] asm("_binary_certs_amazon_root_ca1_pem_start");

static PiezoSensor gSensor(kPiezoPin, kSensorTypePiezo);
static DeviceIdentity gIdentity;
static Uploader* gUploader = nullptr;
static QueueHandle_t gBatchQueue;
static TaskHandle_t gSamplingTask;
static esp_timer_handle_t gSampleTimer;

// --- 可観測性ヘッダ・リモート再起動監視（本線main.cppからの移植） ---
// これまで本線が送っている以下のヘッダを一切送っておらず、dashboard/watchdogから
// 版数・稼働状況が見えなかった（2026-08-12指摘）。ExtraRequestHeaders/
// WatchResponseHeadersの仕組み自体はUploaderの汎用APIなのでbatch-uplink側の
// 変更は不要、本線から値の出し方だけ持ってくる。
static constexpr const char* kFwVersionHeader = "X-Namz-Fw-Version";
static constexpr const char* kUptimeHeader = "X-Namz-Uptime-Us";
static char sUptimeBuf[24];
static constexpr const char* kHeapFreeHeader = "X-Namz-Heap-Free";
static constexpr const char* kHeapMaxblockHeader = "X-Namz-Heap-Maxblock";
static char sHeapFreeBuf[16];
static char sHeapMaxblockBuf[16];
static constexpr const char* kSpillCountHeader = "X-Namz-Spill-Count";
static constexpr const char* kRamQueuedHeader = "X-Namz-Ram-Queued";
static char sSpillCountBuf[16];
static char sRamQueuedBuf[16];
static constexpr const char* kResetReasonHeader = "X-Namz-Reset-Reason";
static char sResetReasonBuf[16] = "UNKNOWN";

static const char* resetReasonToString(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON: return "POWERON";
    case ESP_RST_EXT: return "EXT";
    case ESP_RST_SW: return "SW";
    case ESP_RST_PANIC: return "PANIC";
    case ESP_RST_INT_WDT: return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT: return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_SDIO: return "SDIO";
    default: return "UNKNOWN";
  }
}

static const char* kExtraRequestHeaderNames[] = {kFwVersionHeader, kUptimeHeader,
                                                  kHeapFreeHeader, kHeapMaxblockHeader,
                                                  kResetReasonHeader, kSpillCountHeader,
                                                  kRamQueuedHeader, nullptr};
static const char* kExtraRequestHeaderValues[] = {kFwVersion, sUptimeBuf,
                                                   sHeapFreeBuf, sHeapMaxblockBuf,
                                                   sResetReasonBuf, sSpillCountBuf,
                                                   sRamQueuedBuf};

// リモート再起動要求（docs/remote_restart.md）とpull型OTA更新許可
// （docs/ota.md §2）。どちらも本線main.cppと同じ「バッチ送信レスポンスへの
// 便乗」で気づく。
static constexpr const char* kRestartHeader = "X-Namz-Restart";
static constexpr const char* kOtaVersionHeader = "X-Namz-Ota-Version";
static constexpr const char* kWatchedHeaders[] = {kRestartHeader, kOtaVersionHeader, nullptr};

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

// --- OTA更新の安全な停止・再開（docs/ota.md、本線main.cppから移植） ---
// フラッシュ書き込み中はキャッシュが無効になり命令フェッチが止まるため、
// 100Hzの測定タイマーは転送中に確実に取りこぼす。転送開始時点で一旦止め、
// キューに残っているバッチはLittleFSへ退避してから焼く。
static void pauseSamplingForOta() {
  Serial.println("[ota] start: pausing sampling, flushing queue to spill");
  esp_timer_stop(gSampleTimer);
  // タイマーを止めるとsamplingTaskへの通知も止まり、自分でesp_task_wdt_reset()を
  // 呼べなくなる。転送が終わるまでウォッチドッグの監視対象から一時的に外す。
  esp_task_wdt_delete(gSamplingTask);
  Batch* b = nullptr;
  while (xQueueReceive(gBatchQueue, &b, 0) == pdTRUE) gUploader->enqueue(b);
  size_t flushed = gUploader->flushToSpill();
  Serial.printf("[ota] flushed %u batch(es) to spill\n", (unsigned)flushed);
  // ingest向けの使い回し接続を閉じてからOTA取得へ進む。開けたままだと、これから
  // 張るOTA先(CloudFront)向けの新規TLS接続と2本同時に生きてしまい、TlsMemPool
  // (単一TLS接続前提でサイズを見積もった固定プール)を超えうる（本線と同じ理由。
  // ESP32-C3はRAM総量も少ないため、この対策の重要度はむしろ本線より高い）。
  gUploader->closeConnection();
}

// 成功時はESP.restart()するのでここは通らない。失敗時は測定を止めたままに
// しないよう再開する。
static void resumeSamplingAfterOtaFailure(const char* reason) {
  Serial.printf("[ota] %s: resuming sampling\n", reason);
  esp_task_wdt_add(gSamplingTask);
  esp_timer_start_periodic(gSampleTimer, kSamplePeriodUs);
}

// OTA本体を取得して書き込む。安全停止(pauseSamplingForOta)は呼び出し側の責務。
// TLS検証は本線と同じくAmazon Root CA 1を明示指定する（docs/ota.md §2.6、
// 既定CAバンドルはPlatformIO Arduinoビルドでは機能しないと実機で確認済み）。
static bool performPullOta(const String& targetVersion) {
  char url[256];
  snprintf(url, sizeof(url), "%s/ota/%s/%s.bin", gIdentity.otaBaseUrl.c_str(), kOtaEnv,
           targetVersion.c_str());
  Serial.printf("[ota-pull] fetching %s\n", url);

  WiFiClientSecure client;
  client.setCACert(reinterpret_cast<const char*>(amazon_root_ca1_pem_start));
  httpUpdate.rebootOnUpdate(false);  // 再起動は呼び出し側(checkAndPerformPullOta)で制御する
  httpUpdate.onProgress([](int, int) {
    esp_task_wdt_reset();  // ブロッキングAPIなのでここでWDTを養う
  });

  t_httpUpdate_return ret = httpUpdate.update(client, url);
  if (ret != HTTP_UPDATE_OK) {
    Serial.printf("[ota-pull] failed: %d (%s)\n", (int)ret, httpUpdate.getLastErrorString().c_str());
    return false;
  }
  Serial.println("[ota-pull] write OK, restarting");
  Serial.flush();
  return true;
}

// 失敗後に間を置かず再試行すると、ヘッダ値は次の成功バッチPOSTまで更新されない
// （Uploaderがキャッシュする値）ため、バックオフ無しだと高頻度リトライで測定が
// 止まったままになる（本線が実機で踏んだ不具合、docs/ota.md §2.7）。同じ1分の
// バックオフを踏襲する。
static constexpr int64_t kOtaRetryBackoffUs = 60LL * 1000000LL;

// バージョン不一致を見つけたら、安全停止→取得→(成功なら再起動/失敗なら復旧)まで
// 一息に行う。uploaderTaskのループでバッチ送信レスポンスを見た時に呼ぶ。
static void checkAndPerformPullOta(const String& target) {
  static int64_t sNextAttemptUs = 0;
  if (target.length() == 0 || target == kFwVersion) return;
  int64_t now = esp_timer_get_time();
  if (now < sNextAttemptUs) return;  // 直近の失敗からバックオフ中
  Serial.printf("[ota-pull] update available: %s -> %s\n", kFwVersion, target.c_str());
  pauseSamplingForOta();
  if (performPullOta(target)) {
    esp_task_wdt_reset();
    delay(200);
    ESP.restart();
  } else {
    resumeSamplingAfterOtaFailure("pull failed");
    sNextAttemptUs = now + kOtaRetryBackoffUs;
  }
}

// --- 送信タスク ---
// 本線は「吸い出し」「送信」を2タスクに分けている(LittleFS競合回避、
// docs/log/2026-08-11-uploader-task-split.md)が、ここではまず1タスクに
// まとめる。詰まりが実機で見えたら分割を検討する。
static void uploaderTask(void*) {
  bool restartRequested = false;  // サーバからのリモート再起動要求（docs/remote_restart.md）
  for (;;) {
    Batch* b = nullptr;
    while (xQueueReceive(gBatchQueue, &b, 0) == pdTRUE) {
      gUploader->enqueue(b);
    }
    // 送信直前に稼働時間・ヒープヘッダを更新（Uploaderは値をコピーせずポインタを
    // 保持するため、pump()がPOSTする直前の値を確実に使わせるにはこの位置で書く
    // 必要がある。本線main.cppと同じ理由）。
    snprintf(sUptimeBuf, sizeof(sUptimeBuf), "%lld", (long long)esp_timer_get_time());
    snprintf(sHeapFreeBuf, sizeof(sHeapFreeBuf), "%u", (unsigned)ESP.getFreeHeap());
    snprintf(sHeapMaxblockBuf, sizeof(sHeapMaxblockBuf), "%u", (unsigned)ESP.getMaxAllocHeap());
    snprintf(sSpillCountBuf, sizeof(sSpillCountBuf), "%u", (unsigned)gUploader->spillCount());
    snprintf(sRamQueuedBuf, sizeof(sRamQueuedBuf), "%u", (unsigned)gUploader->ramQueued());
    gUploader->pump();

    // リモート再起動要求: バッチ送信のレスポンスヘッダで気づいたら、RAMキューを
    // LittleFSへ退避してからすぐ再起動する（本線main.cppと同じ「2xxが返るまで
    // 捨てない」不変条件を守った安全な再起動）。
    if (!restartRequested && gUploader->lastResponseHeaderValue(kRestartHeader) == "1") {
      restartRequested = true;
      Serial.println("[uploader] restart requested by server, flushing queue to spill");
    }
    if (restartRequested) {
      Batch* pending = nullptr;
      while (xQueueReceive(gBatchQueue, &pending, 0) == pdTRUE) gUploader->enqueue(pending);
      gUploader->flushToSpill();
      if (gUploader->ramQueued() == 0) {
        Serial.println("[uploader] queue flushed to spill, restarting now");
        Serial.flush();
        delay(200);
        ESP.restart();
      }
    }

    // pull型OTA更新の確認（docs/ota.md §2）。同じバッチ送信レスポンスヘッダで
    // 気づく。不一致なら取得〜書き込みまで一息に行い、完了までここでブロックする
    // （performPullOta内でWDTを養う）。
    checkAndPerformPullOta(gUploader->lastResponseHeaderValue(kOtaVersionHeader));
    delay(50);
  }
}

void setup() {
  Serial.begin(kSerialBaud);
  delay(200);
  Serial.printf("\n[boot] NamazuHaUrokoGaNai piezo fw=%s env=%s\n", kFwVersion, kOtaEnv);

  // ヘッダ送信用の再起動理由をここで確定する(本線main.cppと同じ理由、
  // ネットワーク送信より前の起動直後に1回だけ)。
  snprintf(sResetReasonBuf, sizeof(sResetReasonBuf), "%s", resetReasonToString(esp_reset_reason()));
  Serial.printf("[boot] reset_reason=%s\n", sResetReasonBuf);

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
                           kWatchedHeaders,
                           kExtraRequestHeaderNames, kExtraRequestHeaderValues,
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
