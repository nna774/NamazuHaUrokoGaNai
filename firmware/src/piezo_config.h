#pragma once
// ピエゾ実験機(ESP32-C3スーパーミニ)のパラメータ。
//
// 本線 config.h とは独立（同名定数がinclude時に衝突するため、値が同じでも
// 別ファイルに持つ）。docs/piezo.md §7・docs/design.md「ESP32ボードの差し替え」
// 参照——ESP32-C3はシングルコアで本線とはタスクモデルが異なる。

#include <cstdint>

// --- シリアル ---
static constexpr uint32_t kSerialBaud = 115200;

// --- センサ ---
// GPIO4(ADC1)。docs/piezo.md §4のピン選定・保護回路(Rs=47kΩ・Rb=10MΩ・D1/D2=1N60)を
// 実装した配線を前提にする。
static constexpr int kPiezoPin = 4;
// docs/wire_format.md「sensor_type の帯域」: 128〜249が非校正の生値センサ帯。
static constexpr uint8_t kSensorTypePiezo = 128;

// --- サンプリング ---
// 固有周波数は実測約50Hz(docs/piezo.md §5)。ナイキストに余裕を持たせ本線と
// 同じ100Hzにする。オーバーサンプリングは本線と違い行わない(ノイズ低減より
// まず送信を通すことを優先。必要なら後で追加する)。
static constexpr uint32_t kSampleRateHz = 100;
static constexpr uint32_t kSamplePeriodUs = 1000000UL / kSampleRateHz;

// --- バッチ ---
// 1軸int16(2B/サンプル)なので、本線(3軸int16、18KB/30秒)の1/3の6KB/30秒で済む。
// TLSハンドシェイクのオーバーヘッドは軸数と無関係に一定のため、本線がRAM不足で
// 苦しんだ経験(docs/log/2026-08-10-ota-tls-pool-race.md等)を踏まえ、まずは
// 保守的な値から始める。実機でヒープの空き状況を見ながら調整すること
// (docs/piezo.md §7)。
static constexpr uint32_t kBatchSeconds = 30;
static constexpr uint32_t kBatchSamples = kSampleRateHz * kBatchSeconds;

// --- 送信キュー / ローカルバッファ ---
// 本線の教訓(kMaxRamBatches=2でも一般ヒープが断片化した実機バグ)を踏まえ、
// まず1から始める。溢れた分はLittleFSへ自動退避される(Uploaderの標準機能)。
static constexpr uint32_t kMaxRamBatches = 1;
static constexpr const char* kSpillDir = "/spill";

// --- 時刻同期 ---
static constexpr const char* kNtpServer1 = "ntp.nict.jp";
static constexpr const char* kNtpServer2 = "pool.ntp.org";
static constexpr uint32_t kNtpStepThresholdSeconds = 5;

// --- ビルド版数 ---
// get_fw_version.py(platformio.ini の extra_scripts)がgitの短縮hashを注入する。
static constexpr const char* kFwVersion = NAMZ_FW_VERSION;
