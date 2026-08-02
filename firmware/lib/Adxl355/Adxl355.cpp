#include "Adxl355.h"

bool Adxl355::begin() {
  pinMode(cs_, OUTPUT);
  deselect();
  settings_ = SPISettings(clockHz_, MSBFIRST, SPI_MODE0);

  // 既知の状態から始める（電源を切らずに再起動した場合の残留設定を消す）。
  writeReg(kReset, kResetCode);
  delay(10);

  uint8_t ad = 0, mst = 0, part = 0;
  readIds(ad, mst, part);
  if (ad != kDevidAdValue || mst != kDevidMstValue || part != kPartIdValue) {
    return false;
  }

  writeReg(kFilter, kFilterValue);
  writeReg(kRange, kRangeValue);
  writeReg(kPowerCtl, kPowerCtlValue);
  delay(10);
  return true;
}

void Adxl355::readIds(uint8_t& devidAd, uint8_t& devidMst, uint8_t& partId) {
  uint8_t buf[3];
  readRegs(kDevidAd, buf, sizeof(buf));
  devidAd = buf[0];
  devidMst = buf[1];
  partId = buf[2];
}

bool Adxl355::read(AccelSample& out) {
  uint8_t buf[9];
  readRegs(kXData3, buf, sizeof(buf));
  // 各軸3バイト・ビッグエンディアン。20bit が左詰めなので下位4bitを捨てる。
  auto decode = [](const uint8_t* p) -> int32_t {
    int32_t v = (static_cast<int32_t>(p[0]) << 12) |
                (static_cast<int32_t>(p[1]) << 4) | (p[2] >> 4);
    if (v & 0x80000) v -= 0x100000;  // 20bit 符号拡張
    return v;
  };
  out.x = decode(buf + 0);
  out.y = decode(buf + 3);
  out.z = decode(buf + 6);
  return true;
}

uint8_t Adxl355::readReg(uint8_t reg) {
  uint8_t v = 0;
  readRegs(reg, &v, 1);
  return v;
}

void Adxl355::writeReg(uint8_t reg, uint8_t val) {
  spi_.beginTransaction(settings_);
  select();
  spi_.transfer(static_cast<uint8_t>(reg << 1));  // LSB=0 で書き込み
  spi_.transfer(val);
  deselect();
  spi_.endTransaction();
}

void Adxl355::readRegs(uint8_t reg, uint8_t* buf, size_t len) {
  spi_.beginTransaction(settings_);
  select();
  spi_.transfer(static_cast<uint8_t>((reg << 1) | 1));  // LSB=1 で読み出し
  for (size_t i = 0; i < len; ++i) {
    buf[i] = spi_.transfer(0x00);
  }
  deselect();
  spi_.endTransaction();
}
