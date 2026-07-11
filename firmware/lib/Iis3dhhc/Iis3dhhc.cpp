#include "Iis3dhhc.h"

bool Iis3dhhc::begin() {
  pinMode(cs_, OUTPUT);
  deselect();
  settings_ = SPISettings(clockHz_, MSBFIRST, SPI_MODE3);

  if (whoAmI() != kWhoAmIValue) {
    return false;
  }

  // CTRL_REG1:
  //   bit7 NORM_MOD_EN = 1  … 通常動作有効化（1.1kHz ODR）
  //   bit6 IF_ADD_INC  = 1  … 連続読みでアドレス自動インクリメント
  //   bit3 BDU         = 1  … Block Data Update（読み出し中の更新を防ぐ）
  const uint8_t ctrl1 = 0b10000000 | 0b01000000 | 0b00001000;
  writeReg(kCtrlReg1, ctrl1);
  delay(10);
  return true;
}

uint8_t Iis3dhhc::whoAmI() { return readReg(kWhoAmI); }

bool Iis3dhhc::read(AccelSample& out) {
  uint8_t buf[6];
  readRegs(kOutXL, buf, sizeof(buf));
  // little-endian int16 x,y,z
  int16_t x = static_cast<int16_t>(buf[0] | (buf[1] << 8));
  int16_t y = static_cast<int16_t>(buf[2] | (buf[3] << 8));
  int16_t z = static_cast<int16_t>(buf[4] | (buf[5] << 8));
  out.x = x;
  out.y = y;
  out.z = z;
  return true;
}

uint8_t Iis3dhhc::readReg(uint8_t reg) {
  spi_.beginTransaction(settings_);
  select();
  spi_.transfer(kReadBit | reg);
  uint8_t v = spi_.transfer(0x00);
  deselect();
  spi_.endTransaction();
  return v;
}

void Iis3dhhc::writeReg(uint8_t reg, uint8_t val) {
  spi_.beginTransaction(settings_);
  select();
  spi_.transfer(reg);  // 書き込みは MSB=0
  spi_.transfer(val);
  deselect();
  spi_.endTransaction();
}

void Iis3dhhc::readRegs(uint8_t reg, uint8_t* buf, size_t len) {
  spi_.beginTransaction(settings_);
  select();
  spi_.transfer(kReadBit | reg);
  for (size_t i = 0; i < len; ++i) {
    buf[i] = spi_.transfer(0x00);
  }
  deselect();
  spi_.endTransaction();
}
