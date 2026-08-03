#pragma once
// NAMZ ワイヤ形式を Batch に載せる薄い層。
//
// Batch はレイアウトを知らない汎用バッファなので、「3軸サンプル1個 = 1レコード」
// 「32バイトヘッダの中身」「TLV トレイラーの枠組み」はこちら側の責務になる。
// この分離のおかげで Batch を送信基盤ごと他プロジェクトと共有できる。
// 形式そのものの定義は WireFormat.h、仕様は docs/wire_format.md にある。

#include <cstddef>
#include <cstdint>

#include "Batch.h"
#include "WireFormat.h"

namespace namzwire {

// tail に確保する量。TLV は今のところ温度(4+2バイト)1件だけだが、
// 種別が増えても収まるよう余裕を持たせてある。
static constexpr size_t kMaxTrailerBytes = 32;

// 1レコードの幅。sample_format 0=int16(6B) / 1=int32(12B)。
inline size_t sampleBytes(uint8_t sampleFormat) {
  return sampleFormat == 1 ? 3 * sizeof(int32_t) : 3 * sizeof(int16_t);
}

// このプロジェクト用に寸法を与えた Batch を作る。所有権は呼び出し側。
Batch* newBatch(uint32_t capacitySamples, uint8_t sampleFormat);

// 3軸サンプルを1レコードとして積む。幅は Batch の recordBytes から決まる。
// int16 形式では範囲外の値が飽和ではなく切り詰めになるので、センサ側の
// scaleMgPerLsb で int16 に収まることを保証しておくこと。
bool addSample(Batch& b, int32_t x, int32_t y, int32_t z);

// TLV トレイラーを1件足す。サンプル列の後ろに出る。
// Batch::begin() で消えるので、バッチ毎に入れ直すこと。
bool addTrailer(Batch& b, uint16_t type, const void* data, uint16_t len);

// 32バイトヘッダを書く。**サンプルを積み終えた後・Uploader へ渡す前**に呼ぶ
// （sample_count が確定している必要があるため）。
void fillHeader(Batch& b, uint8_t sensorType, float scaleMgPerLsb,
                uint32_t sampleRateHz, uint32_t deviceId);

}  // namespace namzwire
