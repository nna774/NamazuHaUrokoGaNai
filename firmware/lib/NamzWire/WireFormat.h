#pragma once
// バッチのバイナリ形式 v1。docs/wire_format.md と一致させること。
// ESP32・Lambda(Python) ともリトルエンディアン前提。

#include <cstddef>
#include <cstdint>

static constexpr uint32_t kWireMagic = 0x4E414D5A;  // "NAMZ"
// v2: サンプル列の後ろに TLV トレイラーが付きうる（付かないバッチも v2 で正しい）。
static constexpr uint8_t kWireVersion = 2;
static constexpr size_t kWireHeaderSize = 32;

// --- トレイラー（TLV: [u16 type][u16 len][payload]）---
// 種別はセンサに紐付けない。「ADXL355だから温度がある」ではなく
// 「温度のTLVがあれば温度がある」。読み手は知らない type を len ぶん読み飛ばせる。
static constexpr size_t kTlvHeaderSize = 4;
enum TrailerType : uint16_t {
  // センサ内蔵温度の生値(u16)。バッチ先頭時点の1点。単位はセンサ依存なので
  // ℃への換算はクラウド側で行う（換算定数をファームに焼くと訂正が全機再書き込みになる）。
  kTrailerSensorTemp = 1,
};

#pragma pack(push, 1)
struct BatchHeader {
  uint32_t magic;             // 0
  uint8_t version;            // 4
  uint8_t sensor_type;        // 5
  uint8_t sample_format;      // 6  0=int16, 1=int32
  uint8_t axes;               // 7
  uint64_t batch_start_us;    // 8  先頭サンプルのUNIX時刻[us]
  uint32_t sample_rate_mhz;   // 16 サンプルレート[milli-Hz]
  uint32_t sample_count;      // 20
  float scale_mg_per_lsb;     // 24
  uint32_t device_id;         // 28
};
#pragma pack(pop)

static_assert(sizeof(BatchHeader) == kWireHeaderSize, "BatchHeader must be 32 bytes");
