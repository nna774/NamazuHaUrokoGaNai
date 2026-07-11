#include "Batch.h"

#include <cstring>

Batch::Batch(uint32_t capacitySamples) : capacity_(capacitySamples) {
  size_t total = kWireHeaderSize + static_cast<size_t>(capacitySamples) * kSampleBytes;
  buf_ = static_cast<uint8_t*>(malloc(total));
  if (buf_) {
    std::memset(buf_, 0, kWireHeaderSize);
  }
}

Batch::~Batch() { free(buf_); }

void Batch::begin(uint64_t startUs, uint8_t sensorType, uint8_t sampleFormat,
                  float scaleMgPerLsb, uint32_t sampleRateHz, uint32_t deviceId) {
  startUs_ = startUs;
  count_ = 0;
  BatchHeader h{};
  h.magic = kWireMagic;
  h.version = kWireVersion;
  h.sensor_type = sensorType;
  h.sample_format = sampleFormat;
  h.axes = 3;
  h.batch_start_us = startUs;
  h.sample_rate_mhz = sampleRateHz * 1000;  // Hz -> milli-Hz
  h.sample_count = 0;
  h.scale_mg_per_lsb = scaleMgPerLsb;
  h.device_id = deviceId;
  std::memcpy(buf_, &h, sizeof(h));
}

bool Batch::addSample(int16_t x, int16_t y, int16_t z) {
  if (isFull()) return false;
  uint8_t* p = buf_ + kWireHeaderSize + static_cast<size_t>(count_) * kSampleBytes;
  std::memcpy(p + 0, &x, 2);
  std::memcpy(p + 2, &y, 2);
  std::memcpy(p + 4, &z, 2);
  ++count_;
  return true;
}

const uint8_t* Batch::bytes() {
  // sample_count を確定
  std::memcpy(buf_ + 20, &count_, sizeof(uint32_t));
  return buf_;
}

Batch* Batch::fromBytes(const uint8_t* data, size_t len) {
  if (len < kWireHeaderSize) return nullptr;
  Batch* b = new Batch();
  b->buf_ = static_cast<uint8_t*>(malloc(len));
  if (!b->buf_) {
    delete b;
    return nullptr;
  }
  std::memcpy(b->buf_, data, len);
  b->fixedSize_ = len;
  uint32_t cnt;
  std::memcpy(&cnt, data + 20, sizeof(uint32_t));
  b->count_ = cnt;
  b->capacity_ = cnt;
  std::memcpy(&b->startUs_, data + 8, sizeof(uint64_t));
  return b;
}
