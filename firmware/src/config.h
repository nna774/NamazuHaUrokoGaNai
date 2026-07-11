#pragma once
// ハード・動作パラメータの定数。秘密情報は secrets.h に置く。

#include <cstdint>

// --- サンプリング ---
static constexpr uint32_t kSampleRateHz = 100;
static constexpr uint32_t kSamplePeriodUs = 1000000UL / kSampleRateHz;  // 10ms

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

// --- SPI ピン（ESP32 既定 VSPI）---
static constexpr int kPinSck = 18;
static constexpr int kPinMiso = 19;
static constexpr int kPinMosi = 23;
static constexpr int kPinCsIis3dhhc = 5;
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
