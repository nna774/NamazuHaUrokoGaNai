#pragma once
// ADXL355 (Analog Devices) SPIドライバ。ライブラリ非依存でレジスタ直叩き。
// 想定ボードは EVAL-ADXL355-PMDZ（docs/adxl355.md §4）。
//
// 主要仕様（ADI データシート ADXL355 参照）:
//   - フルスケール可変。本ドライバは最小の ±2.048g 固定（最小レンジ=最小ノイズ）
//   - 20bit 出力 -> 3.90625 µg/LSB
//   - SPI モード0 (CPOL=0, CPHA=0)、最大 10MHz
//   - アドレスは (reg << 1)、LSB が R/W (1=read)。IIS3DHHC の MSB 流儀ではない
//
// IIS3DHHC との差分で転びやすい点は docs/adxl355.md §5.1 にまとめてある。

#include <Arduino.h>
#include <SPI.h>

#include "AccelSensor.h"

class Adxl355 : public AccelSensor {
 public:
  Adxl355(SPIClass& spi, int csPin, uint32_t clockHz)
      : spi_(spi), cs_(csPin), clockHz_(clockHz) {}

  bool begin() override;
  bool read(AccelSample& out) override;
  // ±2.048g / 20bit = 3.90625 µg/LSB = 0.00390625 mg/LSB
  float scaleMgPerLsb() const override { return 0.00390625f; }
  uint8_t sensorType() const override { return 1; /* kSensorAdxl355 */ }
  uint8_t sampleFormat() const override { return 1; /* int32 */ }

  // ID 3種を一括で読む（0xAD / 0x1D / 0xED なら生きている）。
  void readIds(uint8_t& devidAd, uint8_t& devidMst, uint8_t& partId);

 private:
  // レジスタ
  static constexpr uint8_t kDevidAd = 0x00;
  static constexpr uint8_t kXData3 = 0x08;
  static constexpr uint8_t kFilter = 0x28;
  static constexpr uint8_t kRange = 0x2C;
  static constexpr uint8_t kPowerCtl = 0x2D;
  static constexpr uint8_t kReset = 0x2F;

  static constexpr uint8_t kDevidAdValue = 0xAD;
  static constexpr uint8_t kDevidMstValue = 0x1D;
  static constexpr uint8_t kPartIdValue = 0xED;
  static constexpr uint8_t kResetCode = 0x52;

  // FILTER: HPF_CORNER=000(OFF) / ODR_LPF=001(2000Hz, 内部LPF -3dB=500Hz)。
  // HPFは必ずOFF。低域処理は気象庁法のFIRの仕事で、センサ側で位相をいじられると
  // tools/backtest.py の数値照合が壊れる。
  static constexpr uint8_t kFilterValue = 0x01;
  // RANGE: bit[1:0]=01 -> ±2.048g。上位の I2C_HS / INT_POL は SPI では効かない。
  static constexpr uint8_t kRangeValue = 0x01;
  // POWER_CTL: standby=0(measurement) / TEMP_OFF=0 / DRDY_OFF=0
  static constexpr uint8_t kPowerCtlValue = 0x00;

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
