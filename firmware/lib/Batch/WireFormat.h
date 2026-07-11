#pragma once
// バッチのバイナリ形式 v1。docs/wire_format.md と一致させること。
// ESP32・Lambda(Python) ともリトルエンディアン前提。

#include <cstdint>

static constexpr uint32_t kWireMagic = 0x4E414D5A;  // "NAMZ"
static constexpr uint8_t kWireVersion = 1;
static constexpr size_t kWireHeaderSize = 32;

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
