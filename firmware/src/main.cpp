// NamazuHaUrokoGaNai ファームウェア本体。
//
// Core1: 測定タスク（100Hzサンプリング + リアルタイム震度 + 検知）
// Core0: 送信タスク（バッチPOST / NTP / リトライ・バックフィル / WiFi再接続 / OTA更新）
//
// NAMZ_SENSOR_TEST を定義してビルドすると WiFi/送信を行わず
// シリアルに "t_us,x,y,z" を出すだけ（tools/capture_serial.py 用・Phase1）。

#include <Arduino.h>
#include <ArduinoOTA.h>
#include <HTTPUpdate.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_system.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>
#include <time.h>

#include "Batch.h"
#include "DeviceIdentity.h"
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
// OTA更新中フラグ（uploaderTask/Core0が書き、loop/Core1が読む）。trueの間は
// loop()が震度画面の代わりにgDisplay.renderOtaUpdating()を出す。
static volatile bool gOtaInProgress = false;

// ボタン長押しによる緊急手動再起動フラグ（gOtaInProgressとは逆方向、
// loop/Core1が書きuploaderTask/Core0が読む。config.hのkRebootHoldConfirmMs/
// kRebootHoldTriggerMs参照）。
// - gManualRebootArmed    : 確認画面に入った時点でtrueにし、Core0へキューの
//   先回り退避を指示する。キャンセルされても一方向のまま戻さない
//   （flushToSpill()は空キューならほぼ無償なので、Core0側で毎周呼び続けても無害）。
// - gManualRebootConfirmed: さらに閾値を超えて押し続けたらtrueにし、
//   リモート再起動と同じrestartRequestedの仕組みに合流させて実際に再起動する。
static volatile bool gManualRebootArmed = false;
static volatile bool gManualRebootConfirmed = false;

// デバイス識別情報・秘密・エンドポイントURL。setup()の先頭でNVSからロードする
// （旧secrets.h。コンパイル時に埋め込まない理由はdocs/ota.md §7参照）。
static DeviceIdentity gIdentity;

#ifndef NAMZ_SENSOR_TEST
// バッチ送信のレスポンスヘッダで気づく2つの仕組みが乗る（Uploaderは「指定した
// ヘッダの値を読んで返す」だけの汎用API、意味づけは呼び出し側=ここが持つ）。
// - X-Namz-Restart: リモート再起動要求（docs/remote_restart.md）。ingestが
//   立てるのはtools/request_restart.pyで要求した直後の1回だけ（一回性）。
// - X-Namz-Ota-Version: pull型OTA更新許可（docs/ota.md §7）。
//   tools/request_ota.pyで立てた値をデバイスのビルドバージョンと一致するまで
//   ingestが返し続ける（一回性ではない、消費しない）。
static constexpr const char* kRestartHeader = "X-Namz-Restart";
static constexpr const char* kOtaVersionHeader = "X-Namz-Ota-Version";
// batch-uplink v2.0.0以降、watchResponseHeadersはnullptr終端の配列（argv方式）。
// 本数を別引数で渡す必要はない。
static constexpr const char* kWatchedHeaders[] = {kRestartHeader, kOtaVersionHeader, nullptr};

// リクエスト側に乗せて送るヘッダ（batch-uplink v1.6.0のextraRequestHeaders）。
// 今動いているビルド版数(kFwVersion)をingestへ渡し、devicesテーブルに記録させる。
// サーバ側からも「今どのバージョンが動いているか」を見えるようにするための
// 汎用ヘッダで、X-Namz-Ota-Versionの停滞検知が「原因不明」で止まっていた問題
// （docs/ota.md §7 未決事項1）に対する外部可観測性を与える。
static constexpr const char* kFwVersionHeader = "X-Namz-Fw-Version";
// 起動からの経過(us、esp_timer_get_time())を毎バッチ乗せる（docs/uptime.md §2.2）。
// センサ値ではなく「今のプロセスの状態」なのでwireトレイラーではなくヘッダで運ぶ。
// サーバはraw/に保存せず、その場でboot_epoch_usの逆算にだけ使う。
static constexpr const char* kUptimeHeader = "X-Namz-Uptime-Us";
static char sUptimeBuf[24];  // int64 usを文字列化するバッファ（uploaderTaskが毎周更新）
// ヒープ空き容量(docs/design.md「送信の信頼性」未定事項4)。TLS接続使い回し
// (v1.7.0)がバックフィル中の断片化にどう効くか、実機のシリアルログ無しでも
// サーバ側から追えるようにするための可観測性。maxblockは空き合計より断片化の
// 兆候を直接示す(連続TLSハンドシェイクは大きな連続ブロックを要求するため)。
static constexpr const char* kHeapFreeHeader = "X-Namz-Heap-Free";
static constexpr const char* kHeapMaxblockHeader = "X-Namz-Heap-Maxblock";
static char sHeapFreeBuf[16];
static char sHeapMaxblockBuf[16];

// 直前の再起動理由(esp_reset_reason())。WDT panic説（docs/log/2026-08-08-
// wdt-panic-hypothesis.md）とヒープ枯渇説を実機データで切り分けるための可観測性。
// 起動時に1回だけ確定し以後変わらない値だが、kExtraRequestHeaderValues[]の要素は
// 静的初期化時にポインタの値をコピーして持つだけなので、単純な`const char*`変数を
// 後からsetup()で別の文字列リテラルへ差し替えても配列側には反映されない
// （sUptimeBuf等と違い固定アドレスのバッファではないため）。同じ「固定アドレスの
// 中身だけ書き換える」やり方に揃え、バッファへコピーする。
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

// Values側は実行時に書き換わる枠がある(sUptimeBuf・sHeapFreeBuf・sHeapMaxblockBuf)
// ので配列自体はconstexprにできない（Uploaderは値をコピーせずポインタを保持するので、
// 指す先の内容だけ書き換えればよい）。batch-uplink v2.0.0以降、namesはnullptr終端
// （argv方式、本数の上限は無い）。valuesは同じ本数ぶん並べるだけで終端は不要
// （ループはnamesの終端で止まる）。
static const char* kExtraRequestHeaderNames[] = {kFwVersionHeader, kUptimeHeader,
                                                  kHeapFreeHeader, kHeapMaxblockHeader,
                                                  kResetReasonHeader, nullptr};
static const char* kExtraRequestHeaderValues[] = {kFwVersion, sUptimeBuf,
                                                   sHeapFreeBuf, sHeapMaxblockBuf,
                                                   sResetReasonBuf};

// spillも満杯なら最古のバッチから捨てる（無制限にRAMへ積み増してクラッシュするのを防ぐ）。
// gIdentity（NVS由来）が要るので静的初期化ではなくsetup()内で構築する。
static Uploader* gUploader = nullptr;

struct AlertMsg {
  uint64_t us;
  float intensity;
  float peak;
};

static QueueHandle_t gBatchQueue;  // Batch*
static QueueHandle_t gAlertQueue;  // AlertMsg

static char gOtaHostname[16];  // "namazu-<id>"
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
                             kSampleRateHz, gIdentity.deviceId);
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
  WiFi.begin(gIdentity.wifiSsid.c_str(), gIdentity.wifiPass.c_str());
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

// --- OTA更新の安全な停止・再開（push/pull共通。docs/ota.md）---
// フラッシュ書き込み中はキャッシュが無効になり両コアの命令フェッチが止まるため、
// 100Hzの測定タイマーは転送中に確実に取りこぼす。転送開始時点で一旦止め、RAMキュー
// のバッチはLittleFSへ退避してから焼く（電源断・パニックでも失わないようにする）。
static void pauseSamplingForOta() {
  Serial.println("[ota] start: pausing sampling, flushing queue to spill");
  gOtaInProgress = true;  // loop()に震度画面から更新中画面への切り替えを伝える
  esp_timer_stop(gSampleTimer);
  // タイマーを止めるとsamplingTaskへの通知も止まり、自分でesp_task_wdt_reset()を
  // 呼べなくなる。転送が終わる（成功時は再起動、失敗時はresumeSamplingで再開）まで
  // ウォッチドッグの監視対象から一時的に外す。
  esp_task_wdt_delete(gSamplingTask);
  Batch* b = nullptr;
  while (xQueueReceive(gBatchQueue, &b, 0) == pdTRUE) gUploader->enqueue(b);
  size_t flushed = gUploader->flushToSpill();
  Serial.printf("[ota] flushed %u batch(es) to spill\n", (unsigned)flushed);
}

// 成功時はESP.restart()するのでここは通らない。失敗時は測定を止めたままに
// しないよう再開する。
static void resumeSamplingAfterOtaFailure(const char* reason) {
  Serial.printf("[ota] %s: resuming sampling\n", reason);
  esp_task_wdt_add(gSamplingTask);
  esp_timer_start_periodic(gSampleTimer, kReadPeriodUs);
  gOtaInProgress = false;  // 失敗して測定を再開したので震度画面に戻す
}

static void otaOnStart() { pauseSamplingForOta(); }

static void otaOnProgress(unsigned int done, unsigned int total) {
  // 転送は呼び出し元(uploaderTask)のループ内で丸ごとブロックするので、ここで
  // 都度リセットしないとタスクウォッチドッグ(10秒)に落ちる。
  esp_task_wdt_reset();
  static uint8_t lastPct = 255;
  uint8_t pct = total ? (uint8_t)(done * 100U / total) : 0;
  if (pct != lastPct) {
    Serial.printf("[ota] progress %u%%\n", pct);
    lastPct = pct;
  }
}

static void otaOnError(ota_error_t error) {
  char reason[32];
  snprintf(reason, sizeof(reason), "push error %u", (unsigned)error);
  resumeSamplingAfterOtaFailure(reason);
}

// --- OTA更新の待ち受け（HTTPS pull、外出先からの更新・無人運用向け。docs/ota.md §7）---
// 手元から tools/request_ota.py で許可したバージョンを、リモート再起動要求と同じ
// 経路（バッチ送信レスポンスへの便乗、X-Namz-Ota-Version）で知る。再起動要求と
// 違い「消費しない」——ターゲットは「あるべき状態」なので、デバイスが実際にその
// バージョンで起動するまで照合し続けてよい。取得・書き込み失敗時の自然な
// リトライにもなる。ヘッダは gUploader->lastResponseHeaderValue() 経由で読む
// （batch-uplink v1.5.0 で複数ヘッダ監視に対応した）。

// firmware/certs/amazon_root_ca1.pem を platformio.ini の board_build.embed_txtfiles
// でリンクしたバイナリの先頭/終端（config.h参照）。
extern const uint8_t amazon_root_ca1_pem_start[] asm("_binary_certs_amazon_root_ca1_pem_start");
extern const uint8_t amazon_root_ca1_pem_end[] asm("_binary_certs_amazon_root_ca1_pem_end");

// OTA本体を取得して書き込む。安全停止(pauseSamplingForOta)は呼び出し側の責務。
// 成功時はtrueを返す（呼び出し側がESP.restart()する）。失敗時はfalseを返す
// （呼び出し側がresumeSamplingAfterOtaFailureを呼ぶ）。
//
// TLS検証の経緯（実機で2段階の失敗を踏んでいる。docs/ota.md §7）:
// 1. ESP-IDFの低レベルAPI(esp_https_ota_begin/perform/finish +
//    esp_http_client_config_t.crt_bundle_attach)で試したが、device2実機で
//    "Failed to attach bundle" のままTLSハンドシェイクが常に失敗した。
// 2. Arduino-ESP32の`HTTPUpdate`（`WiFiClientSecure`+`HTTPClient`経由）に
//    切り替えたが、`setInsecure()`を呼ばない既定CAバンドル検証も同じ理由で
//    失敗した（"start_ssl_client: -1"）——PlatformIO Arduinoフレームワークの
//    ビルドでは、既定CAバンドルの実体を生成するesp-idf側のcmakeステップが
//    走らず、空のままリンクされていると見られる。
// 結論として、`namazu.dark-kuins.net`実機で証明書チェーンを確認
// (`openssl s_client -showcerts`)し、ルートCA(Amazon Root CA 1)を1本だけ
// `setCACert()`で明示指定する方式にした。これはUploaderの`setInsecure()`
// より厳格（正規のTLS検証）。
static bool performPullOta(const String& targetVersion) {
  char url[256];
  snprintf(url, sizeof(url), "%s/ota/%s/%s.bin", gIdentity.otaBaseUrl.c_str(), kOtaEnv,
           targetVersion.c_str());
  Serial.printf("[ota-pull] fetching %s\n", url);

  WiFiClientSecure client;
  client.setCACert(reinterpret_cast<const char*>(amazon_root_ca1_pem_start));
  httpUpdate.rebootOnUpdate(false);  // 再起動は呼び出し側(checkAndPerformPullOta)で制御する
  httpUpdate.onProgress([](int, int) {
    esp_task_wdt_reset();  // ブロッキングAPIなのでここでWDTを養う(otaOnProgressと同じ理由)
  });

  t_httpUpdate_return ret = httpUpdate.update(client, url);
  if (ret != HTTP_UPDATE_OK) {
    Serial.printf("[ota-pull] failed: %d (%s)\n", (int)ret,
                  httpUpdate.getLastErrorString().c_str());
    return false;
  }
  Serial.println("[ota-pull] write OK, restarting");
  Serial.flush();
  return true;
}

// 失敗後に間を置かず取得を再試行すると、ヘッダ値は次の成功バッチPOSTまで
// 更新されないため（Uploaderがキャッシュする値なので）、この関数はuploaderTask
// のループで毎回呼ばれ続ける。バックオフ無しだと1周(50ms+ネットワーク待ち)ごとに
// 取得を試み、測定タイマーが止まったまま(pauseSamplingForOta中)になり続けて
// 実測が止まる（実機で踏んだ。docs/ota.md §7）。
static constexpr int64_t kOtaRetryBackoffUs = 60LL * 1000000LL;  // 1分

// バージョン不一致を見つけたら、安全停止→取得→(成功なら再起動/失敗なら復旧)まで
// 一息に行う。uploaderTaskのループでバッチ送信レスポンスを見た時に呼ぶ。
//
// 時刻源は esp_timer_get_time()（int64 us、事実上折り返さない）。以前は millis()
// （uint32 ms、約49.7日で折り返す）で「加算した期限」と「今」を直接比較しており、
// 49.7日境界をまたぐ最大60秒の窓でバックオフが早期満了と誤判定されうるバグが
// あった（稼働時間トレイラーの調査の副産物。docs/uptime.md §5）。
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

// --- 送信タスク（Core0）---
static void uploaderTask(void*) {
  esp_task_wdt_add(nullptr);
  uint32_t lastResync = 0;
  bool restartRequested = false;  // サーバからのリモート再起動要求（docs/remote_restart.md）

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

    // OTA更新の待ち受け（LAN内push）。通常は着信確認だけの軽い呼び出しだが、
    // 実際に転送が始まると完了までこの呼び出し内でブロックする
    // （otaOnProgressでWDTを養う）。
    ArduinoOTA.handle();

    // batchQueue -> uploader
    Batch* b = nullptr;
    while (xQueueReceive(gBatchQueue, &b, 0) == pdTRUE) {
      gUploader->enqueue(b);
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
                       (unsigned)gIdentity.deviceId, (unsigned long long)m.us,
                       m.intensity, m.peak);
      bool ok = gUploader->sendAlert(json, n);
      esp_task_wdt_reset();
      Serial.printf("[alert] I=%.1f peak=%.2fgal sent=%d\n", m.intensity, m.peak, ok);
    }

    // 送信直前に稼働時間・ヒープヘッダを更新（Uploaderは値をコピーせずポインタを
    // 保持するため、pump()がPOSTする直前の値を確実に使わせるにはこの位置で書く
    // 必要がある）。
    snprintf(sUptimeBuf, sizeof(sUptimeBuf), "%lld", (long long)esp_timer_get_time());
    snprintf(sHeapFreeBuf, sizeof(sHeapFreeBuf), "%u", (unsigned)ESP.getFreeHeap());
    snprintf(sHeapMaxblockBuf, sizeof(sHeapMaxblockBuf), "%u", (unsigned)ESP.getMaxAllocHeap());
    gUploader->pump();
    esp_task_wdt_reset();

    // リモート再起動要求: バッチ送信のレスポンスヘッダで気づいたら、RAMキューを
    // LittleFSへ退避してからすぐ再起動する（OTAのotaOnStartと同じ安全策。
    // 通信を待たないので数秒で落とせる）。退避済みデータはUploaderの不変条件
    // 「2xxが返るまで捨てない」どおり、再起動後の通常のバックフィルで送信が続く。
    if (!restartRequested && gUploader->lastResponseHeaderValue(kRestartHeader) == "1") {
      restartRequested = true;
      Serial.println("[uploader] restart requested by server, flushing queue to spill");
    }
    // 緊急手動再起動（ボタン長押し。docs/log/2026-08-08-emergency-reboot-button.md）。
    // 確認画面に入った時点(gManualRebootArmed)で先回り退避を始め、閾値を超えて
    // 押し続けた確定(gManualRebootConfirmed)でrestartRequestedに合流させる。
    // リモート再起動と同じ「2xxが返るまで捨てない」不変条件のまま安全に再起動する。
    if (!restartRequested && gManualRebootArmed) {
      gUploader->flushToSpill();
    }
    if (!restartRequested && gManualRebootConfirmed) {
      restartRequested = true;
      Serial.println("[uploader] manual reboot confirmed via button hold, flushing queue to spill");
    }
    if (restartRequested) {
      // gBatchQueueはこの周のループ冒頭で既にuploaderへ吸い出し済み。
      gUploader->flushToSpill();
      if (gUploader->ramQueued() == 0) {
        Serial.println("[uploader] queue flushed to spill, restarting now");
        Serial.flush();
        esp_task_wdt_reset();
        delay(200);
        ESP.restart();
      }
    }

    // pull型OTA更新の確認（docs/ota.md §7）。同じバッチ送信レスポンスヘッダで
    // 気づく。不一致なら取得〜書き込みまで一息に行い、完了までここでブロック
    // する（performPullOta内でWDTを養う）。
    checkAndPerformPullOta(gUploader->lastResponseHeaderValue(kOtaVersionHeader));

    delay(50);
  }
}
#endif

void setup() {
  Serial.begin(kSerialBaud);
  delay(200);
  Serial.printf("\n[boot] NamazuHaUrokoGaNai fw=%s env=%s\n", kFwVersion, kOtaEnv);
#ifndef NAMZ_SENSOR_TEST
  // resetReasonToString/sResetReasonBufはUploaderへ送るヘッダ用で、ネットワーク
  // 送信の無いsensortestビルドには存在しない（上のkExtraRequestHeaderNames等と
  // 同じ#ifndefで囲まれている）。
  snprintf(sResetReasonBuf, sizeof(sResetReasonBuf), "%s",
           resetReasonToString(esp_reset_reason()));
  Serial.printf("[boot] reset_reason=%s\n", sResetReasonBuf);
#endif

  // デバイス識別情報・秘密・エンドポイントURLをNVSからロードする（docs/ota.md §7）。
  // 失敗時はdeviceId=0のまま返る。表示のIDだけはこの時点で使うが、実際に
  // 空のまま進めてよいかは下のガード（NAMZ_SENSOR_TEST以外）でチェックする。
  loadDeviceIdentity(gIdentity);
  gDisplay.begin(gIdentity.deviceId);
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
  // WiFi/HMAC/送信先が空のまま進むと不定動作になる（未プロビジョニング）。
  // tools/provision_device.py provision-h --id N → pio run -e provision -t upload
  // を先にやれ（docs/ota.md §7）。
  if (gIdentity.deviceId == 0 || gIdentity.wifiSsid.length() == 0 ||
      gIdentity.hmacSecret.length() == 0 || gIdentity.ingestUrl.length() == 0) {
    for (;;) {
      Serial.println("[boot] device identity not provisioned in NVS. halting.");
      delay(5000);
    }
  }

  gBatchQueue = xQueueCreate(4, sizeof(Batch*));
  gAlertQueue = xQueueCreate(4, sizeof(AlertMsg));
  connectWifi();
  timesync::begin(kNtpServer1, kNtpServer2,
                  static_cast<uint64_t>(kNtpStepThresholdSeconds) * 1000000ULL);
  // ingest/alert先はLambda Function URL直（*.lambda-url.ap-northeast-1.on.aws、
  // CloudFrontを介さない）。openssl s_clientで実機のチェーンを確認したところ
  // leaf -> Amazon RSA 2048 M01 -> Amazon Root CA 1 で、OTA用に埋め込み済みの
  // 同じルートCAで検証できる（ドメインは別だがどちらもAWS/ACM発行のため）。
  gUploader = new Uploader(gIdentity.ingestUrl.c_str(), gIdentity.alertUrl.c_str(),
                           gIdentity.hmacSecret.c_str(), gIdentity.deviceId,
                           kMaxRamBatches, kSpillDir, /*dropOldestWhenFull=*/true,
                           kWatchedHeaders,
                           kExtraRequestHeaderNames, kExtraRequestHeaderValues,
                           reinterpret_cast<const char*>(amazon_root_ca1_pem_start));
  gUploader->begin();

  // OTA更新（docs/ota.md）。ArduinoOTA.handle()はuploaderTask（Core0）で回す。
  snprintf(gOtaHostname, sizeof(gOtaHostname), "namazu-%u", (unsigned)gIdentity.deviceId);
  ArduinoOTA.setHostname(gOtaHostname);
  ArduinoOTA.setPassword(gIdentity.otaPassword.c_str());
  ArduinoOTA.onStart(otaOnStart);
  ArduinoOTA.onProgress(otaOnProgress);
  ArduinoOTA.onError(otaOnError);
  ArduinoOTA.begin();
  Serial.printf("[ota] ready as %s.local\n", gOtaHostname);

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

#ifndef NAMZ_SENSOR_TEST
  // ボタン長押しでの緊急手動再起動（config.hのkRebootHoldConfirmMs/
  // kRebootHoldTriggerMs参照）。
  //
  // 画面反転は元の挙動どおり押した瞬間(press edge)に常に行う。離した瞬間
  // (release edge)を条件に入れると、離す瞬間の接点バウンスでrelease edgeが
  // 複数回検出され、反転が偶数回起きて相殺され「効かなくなる」不具合を実機で
  // 踏んだ（press edgeなら旧実装と同じで実績あり）。confirm閾値に達して
  // 確認画面(黄)へ入る時にもう一度toggleFlip()し、押し始めの反転を打ち消す
  // （今の画面を見たまま押し始めるため、押す前後で向きが変わって見えると
  // 分かりづらいと指摘を受けた。打ち消すまでの一瞬だけ反転して見えるのは許容）。
  //
  // 押し続けてconfirm閾値を超えたら確認画面に切り替え、その時点で
  // uploaderTask(Core0)へキューの先回り退避を指示する(gManualRebootArmed)。
  // さらにtrigger閾値まで押し続けたら実際の再起動を指示する
  // (gManualRebootConfirmed)。確認画面に入った後でも、trigger閾値に達する前に
  // 離せば即座にキャンセルして通常表示に戻す（既にflushしていても実害は無い）。
  static uint32_t pressStartMs = 0;
  static bool rebootArmed = false;  // 確認画面(黄)を出すべきか。離せば即falseに戻す
  bool pressed = digitalRead(kPinButtonFlip) == LOW;
  uint32_t nowMsButton = millis();
  uint32_t holdMs = 0;
  if (pressed && !prevPressed) {
    pressStartMs = nowMsButton;
    rebootArmed = false;
    gDisplay.toggleFlip();
  }
  if (pressed) {
    holdMs = nowMsButton - pressStartMs;
    if (!rebootArmed && holdMs >= kRebootHoldConfirmMs) {
      rebootArmed = true;
      gManualRebootArmed = true;
      // 押し始めのtoggleFlip()を打ち消し、確認画面(黄)は押す前の向きで出す
      // （押しっぱなしの画面を見ている最中に反転すると分かりづらいと指摘を受けた。
      // 打ち消すまでの一瞬だけ反転して見えるのは許容）。
      gDisplay.toggleFlip();
    }
    if (rebootArmed && holdMs >= kRebootHoldTriggerMs) {
      gManualRebootConfirmed = true;
    }
  }
  if (!pressed && prevPressed) {
    rebootArmed = false;  // 確認画面のまま離したらキャンセル、通常表示に戻す
  }
  prevPressed = pressed;
#else
  // ボタン押下エッジで画面反転
  bool pressed = digitalRead(kPinButtonFlip) == LOW;
  if (pressed && !prevPressed) gDisplay.toggleFlip();
  prevPressed = pressed;
#endif

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
    if (rebootArmed) {
      // ボタン長押し中: 確認画面（黄）に切り替え、あと何秒でtrigger閾値に
      // 達するかを出す。trigger閾値到達後はCore0が退避完了を待っているだけ
      // なので「REBOOTING」に切り替える。
      bool confirmed = holdMs >= kRebootHoldTriggerMs;
      uint32_t remainMs = confirmed ? 0 : (kRebootHoldTriggerMs - holdMs);
      uint32_t remainSeconds = (remainMs + 999) / 1000;  // 切り上げでカウントダウン表示
      gDisplay.renderRebootHold(clock, confirmed, remainSeconds);
    } else if (gOtaInProgress) {
      // OTA転送中は測定タイマーが止まっており震度・WiFi・バックログの値が
      // 意味を持たないため、震度画面の代わりに更新中であることだけを大きく出す。
      gDisplay.renderOtaUpdating(clock);
    } else {
      bool wifi = WiFi.status() == WL_CONNECTED;
      String ip = wifi ? WiFi.localIP().toString() : String("");
      uint32_t backlog = gUploader->spillCount() + gUploader->ramQueued();
      uint32_t backlogAgeS = 0;
      uint64_t oldestUs;
      if (backlog > 0 && timesync::isSynced() &&
          gUploader->oldestQueuedStartUs(oldestUs)) {
        uint64_t nowUs = timesync::nowUs();
        backlogAgeS = nowUs > oldestUs ? (uint32_t)((nowUs - oldestUs) / 1000000ULL) : 0;
      }
      gDisplay.render(gDispIntensity, gDispPeakGal, wifi, ip, backlog, backlogAgeS,
                      status, bg, clock);
    }
#endif
  }
  vTaskDelay(pdMS_TO_TICKS(250));
}
