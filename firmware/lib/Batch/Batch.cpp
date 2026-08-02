#include "Batch.h"

#include <cstring>

Batch::Batch(uint32_t capacitySamples, uint8_t sampleFormat)
    : sampleFormat_(sampleFormat),
      sampleBytes_(sampleBytesFor(sampleFormat)),
      capacity_(capacitySamples) {
  size_t total = kWireHeaderSize + static_cast<size_t>(capacitySamples) * sampleBytes_
                 + kMaxTrailerBytes;
  buf_ = static_cast<uint8_t*>(malloc(total));
  if (buf_) {
    std::memset(buf_, 0, kWireHeaderSize);
  }
}

Batch::~Batch() { free(buf_); }

void Batch::begin(uint64_t startUs, uint8_t sensorType, float scaleMgPerLsb,
                  uint32_t sampleRateHz, uint32_t deviceId) {
  startUs_ = startUs;
  count_ = 0;
  trailerLen_ = 0;
  BatchHeader h{};
  h.magic = kWireMagic;
  h.version = kWireVersion;
  h.sensor_type = sensorType;
  h.sample_format = sampleFormat_;
  h.axes = 3;
  h.batch_start_us = startUs;
  h.sample_rate_mhz = sampleRateHz * 1000;  // Hz -> milli-Hz
  h.sample_count = 0;
  h.scale_mg_per_lsb = scaleMgPerLsb;
  h.device_id = deviceId;
  std::memcpy(buf_, &h, sizeof(h));
}

bool Batch::addSample(int32_t x, int32_t y, int32_t z) {
  if (isFull()) return false;
  uint8_t* p = buf_ + kWireHeaderSize + static_cast<size_t>(count_) * sampleBytes_;
  if (sampleFormat_ == 1) {
    std::memcpy(p + 0, &x, 4);
    std::memcpy(p + 4, &y, 4);
    std::memcpy(p + 8, &z, 4);
  } else {
    int16_t v[3] = {static_cast<int16_t>(x), static_cast<int16_t>(y),
                    static_cast<int16_t>(z)};
    std::memcpy(p, v, sizeof(v));
  }
  ++count_;
  return true;
}

bool Batch::addTrailer(uint16_t type, const void* data, uint16_t len) {
  if (trailerLen_ + kTlvHeaderSize + len > kMaxTrailerBytes) return false;
  uint8_t* p = trailer_ + trailerLen_;
  std::memcpy(p + 0, &type, 2);
  std::memcpy(p + 2, &len, 2);
  std::memcpy(p + 4, data, len);
  trailerLen_ += kTlvHeaderSize + len;
  return true;
}

const uint8_t* Batch::bytes() {
  // sample_count を確定
  std::memcpy(buf_ + 20, &count_, sizeof(uint32_t));
  // トレイラーはサンプル列の直後。位置は count_ が決まって初めて確定する。
  if (trailerLen_) {
    std::memcpy(buf_ + kWireHeaderSize + static_cast<size_t>(count_) * sampleBytes_,
                trailer_, trailerLen_);
  }
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
  b->sampleFormat_ = data[6];  // BatchHeader::sample_format
  b->sampleBytes_ = sampleBytesFor(b->sampleFormat_);
  uint32_t cnt;
  std::memcpy(&cnt, data + 20, sizeof(uint32_t));
  b->count_ = cnt;
  b->capacity_ = cnt;
  std::memcpy(&b->startUs_, data + 8, sizeof(uint64_t));
  return b;
}
