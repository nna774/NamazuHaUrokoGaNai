#pragma once
// ハード・動作パラメータの定数。秘密情報は secrets.h に置く。

#include <cstdint>

// --- シリアル ---
// クローンボードのUSB-シリアル変換は921600だと化けるため115200にする。
static constexpr uint32_t kSerialBaud = 115200;

// --- サンプリング ---
static constexpr uint32_t kSampleRateHz = 100;
static constexpr uint32_t kSamplePeriodUs = 1000000UL / kSampleRateHz;  // 出力周期 10ms

// --- オーバーサンプリング ---
// センサを出力レートの kOversample 倍(=1kHz)で読み、平均して100Hzに間引く。
// 50Hz超のエイリアシングを抑え、白色ノイズを約√kOversample 倍下げる。
static constexpr uint32_t kOversample = 10;
static constexpr uint32_t kReadPeriodUs = kSamplePeriodUs / kOversample;  // 読み周期 1ms

// --- バッチ ---
static constexpr uint32_t kBatchSeconds = 30;
static constexpr uint32_t kBatchSamples = kSampleRateHz * kBatchSeconds;  // 3000

// --- 送信キュー / ローカルバッファ ---
// RAM上に保持する未送信バッチ数。これを超えたら LittleFS へ退避する。
static constexpr uint32_t kMaxRamBatches = 6;
static constexpr const char* kSpillDir = "/spill";
static constexpr uint32_t kMaxSpillBatches = 20000;  // 90日ぶんの上限目安

// --- リアルタイム検知 ---
// リアルタイム震度がこの値以上の状態が kAlertHoldSeconds 続いたらデバイス速報を出す。
static constexpr float kAlertIntensity = 0.5f;
static constexpr float kAlertHoldSeconds = 2.0f;
// 同一イベントの再通知を抑制するクールダウン。
static constexpr float kAlertCooldownSeconds = 30.0f;

// --- SPI ピン ---
// TTGO T-Display 系ボード向け。既定の 18/19/23/5 は基板上の TFT(ST7789) が
// 内部で使っておりピンヘッダに出ていないため、出力可能な空きピンへ割り当てる。
// (36/37/38/39 は入力専用なので SCK/MOSI/CS には使えない)
// 無印 WROOM-32 DevKit を使う場合は 18/19/23/5 に戻してよい。
static constexpr int kPinSck = 25;
static constexpr int kPinMiso = 27;
static constexpr int kPinMosi = 26;
static constexpr int kPinCsIis3dhhc = 33;
static constexpr uint32_t kSpiClockHz = 8000000;  // 8MHz

// --- センサ種別（ワイヤフォーマットと一致させる）---
enum SensorType : uint8_t {
  kSensorIis3dhhc = 0,
  kSensorAdxl355 = 1,
  kSensorLsm6dso = 2,
};

// --- 時刻同期 ---
static constexpr const char* kNtpServer1 = "ntp.nict.jp";
static constexpr const char* kNtpServer2 = "pool.ntp.org";
static constexpr uint32_t kNtpResyncSeconds = 3600;  // 1時間ごと

// secrets.h（gitignore対象）で定義する:
//   kWifiSsid, kWifiPass, kIngestUrl, kAlertUrl, kDeviceId, kHmacSecret
#include "secrets.h"
