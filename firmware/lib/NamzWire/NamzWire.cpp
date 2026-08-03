#include "NamzWire.h"

#include <cstring>

namespace namzwire {

Batch* newBatch(uint32_t capacitySamples, uint8_t sampleFormat) {
  return new Batch(capacitySamples, sampleBytes(sampleFormat), kWireHeaderSize,
                   kMaxTrailerBytes);
}

bool addSample(Batch& b, int32_t x, int32_t y, int32_t z) {
  if (b.recordBytes() == 3 * sizeof(int32_t)) {
    int32_t v[3] = {x, y, z};
    return b.addRecord(v, sizeof(v));
  }
  int16_t v[3] = {static_cast<int16_t>(x), static_cast<int16_t>(y),
                  static_cast<int16_t>(z)};
  return b.addRecord(v, sizeof(v));
}

bool addTrailer(Batch& b, uint16_t type, const void* data, uint16_t len) {
  // TLV はヘッダと payload で1件。片方だけ入った中途半端な tail を残さないよう、
  // 書き始める前に総量で判定する。
  if (b.tailRemaining() < kTlvHeaderSize + len) return false;
  uint8_t tlv[kTlvHeaderSize];
  std::memcpy(tlv + 0, &type, 2);
  std::memcpy(tlv + 2, &len, 2);
  b.appendTail(tlv, sizeof(tlv));
  b.appendTail(data, len);
  return true;
}

void fillHeader(Batch& b, uint8_t sensorType, float scaleMgPerLsb,
                uint32_t sampleRateHz, uint32_t deviceId) {
  BatchHeader h{};
  h.magic = kWireMagic;
  h.version = kWireVersion;
  h.sensor_type = sensorType;
  h.sample_format = b.recordBytes() == 3 * sizeof(int32_t) ? 1 : 0;
  h.axes = 3;
  h.batch_start_us = b.startUs();
  h.sample_rate_mhz = sampleRateHz * 1000;  // Hz -> milli-Hz
  h.sample_count = b.recordCount();
  h.scale_mg_per_lsb = scaleMgPerLsb;
  h.device_id = deviceId;
  std::memcpy(b.headerPtr(), &h, sizeof(h));
}

}  // namespace namzwire
