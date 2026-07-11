#pragma once
// IIS3DHHC (STMicroelectronics) SPIドライバ。ライブラリ非依存でレジスタ直叩き。
//
// 主要仕様（ST データシート DS12084 参照）:
//   - フルスケール固定 ±2.5g、16bit -> 0.076 mg/LSB
//   - 出力データレート 1.1kHz 固定（本システムは100Hzでポーリング）
//   - SPI モード3 (CPOL=1, CPHA=1)、最大 ~10MHz
//   - 読み出しは MSB=1 でアドレス、IF_ADD_INC で連続読み

#include <SPI.h>

#include "AccelSensor.h"

class Iis3dhhc : public AccelSensor {
 public:
  Iis3dhhc(SPIClass& spi, int csPin, uint32_t clockHz)
      : spi_(spi), cs_(csPin), clockHz_(clockHz) {}

  bool begin() override;
  bool read(AccelSample& out) override;
  float scaleMgPerLsb() const override { return 0.076f; }
  uint8_t sensorType() const override { return 0; /* kSensorIis3dhhc */ }
  uint8_t sampleFormat() const override { return 0; /* int16 */ }

  uint8_t whoAmI();

 private:
  // レジスタ
  static constexpr uint8_t kWhoAmI = 0x0F;
  static constexpr uint8_t kWhoAmIValue = 0x11;
  static constexpr uint8_t kCtrlReg1 = 0x20;
  static constexpr uint8_t kOutXL = 0x28;
  static constexpr uint8_t kReadBit = 0x80;

  uint8_t readReg(uint8_t reg);
  void writeReg(uint8_t reg, uint8_t val);
  void readRegs(uint8_t reg, uint8_t* buf, size_t len);
  void select() { digitalWrite(cs_, LOW); }
  void deselect() { digitalWrite(cs_, HIGH); }

  SPIClass& spi_;
  int cs_;
  uint32_t clockHz_;
  SPISettings settings_;
};
