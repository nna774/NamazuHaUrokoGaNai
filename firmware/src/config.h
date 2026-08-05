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
// int32 センサ(ADXL355)は 1サンプル12バイトで int16 機の倍を食う。30秒だと 36KB/本
// になり、「送信待ち1本＋充填中1本」の最小構成でも 72KB を占めて mbedTLS の
// ハンドシェイクが確保に失敗する（実機で BIGNUM - Memory allocation failed）。
// バッチ長を半分にして 18KB/本 に戻す。int16 機と同じ重さになる。
// ワイヤ形式は sample_count をヘッダに持つので、長さが変わってもクラウドは無変更。
#ifdef NAMZ_SENSOR_ADXL355
static constexpr uint32_t kBatchSeconds = 15;
#else
static constexpr uint32_t kBatchSeconds = 30;
#endif
static constexpr uint32_t kBatchSamples = kSampleRateHz * kBatchSeconds;

// --- 送信キュー / ローカルバッファ ---
// RAM上に保持する未送信バッチ数。これを超えたら LittleFS へ退避する。
// ADXL355 は 18KB/本(15秒×12B)で int16 機と同じ重さだが、本数は少なめにしておく。
// WiFi断からの復旧時、溜まったバッチを抱えたまま TLS ハンドシェイクをやることになる
// ため、ここを高くすると復旧できないまま詰まる。溢れたぶんは LittleFS へ逃げるので
// データは落ちない。
#ifdef NAMZ_SENSOR_ADXL355
static constexpr uint32_t kMaxRamBatches = 3;
#else
static constexpr uint32_t kMaxRamBatches = 6;
#endif
static constexpr const char* kSpillDir = "/spill";

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
// ADXL355 は別CSにしておく。比較フェーズで同じバスに両方ぶら下げても衝突しない。
static constexpr int kPinCsAdxl355 = 32;
static constexpr uint32_t kSpiClockHz = 8000000;  // 8MHz（ADXL355の上限10MHzにも収まる）

// --- ボタン（TTGO T-Display 左ボタン=GPIO0。押すと画面反転）---
// GPIO0は起動時のストラップだが、起動後の押下ではブートローダに入らない。
static constexpr int kPinButtonFlip = 0;

// 表示の「継続」判定（デバイス表示用。クラウドのセッションマージとは別物）。
// 60秒窓の計測震度は揺れ停止後もしばらく高いままなので、"今揺れているか"は
// 瞬時のフィルタ後合成加速度[gal]で判定する。これがしきい値を超えた最終時刻から
// kShakeHangoverMs 以内なら ACTIVE、超えて kDispCloseSeconds 経過で idle。
static constexpr float kDispActiveGal = 1.0f;
static constexpr uint32_t kShakeHangoverMs = 2000;
static constexpr uint32_t kDispCloseSeconds = 30;

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
// このオフセット[s]を超えるずれは slew では詰まらないので一度だけ step で補正する。
// これ未満はSMOOTHのslewに任せ、測定中の時刻ジャンプを避ける。水晶ドリフトは
// ppm級(1時間で数ms)なので通常この閾値には掛からない。
static constexpr uint32_t kNtpStepThresholdSeconds = 5;

// secrets.h（gitignore対象）で定義する:
//   kWifiSsid, kWifiPass, kIngestUrl, kAlertUrl, kDeviceId, kHmacSecret
#include "secrets.h"
