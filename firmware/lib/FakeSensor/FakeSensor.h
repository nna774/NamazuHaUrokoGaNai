#pragma once
// 実センサ無しでパイプライン(サンプリング→バッチ→送信)だけを試すための
// ダミーセンサ。静穏なノイズ(重力ベースライン±小揺らぎ)しか出さないため、
// 震度検知の閾値(kAlertIntensity)には掛からない——イベント判定の特別扱いを
// サーバ側に足さずに済む。newBatchプール検証(docs/log/2026-08-10-
// newbatch-buffer-pool-handoff.md)用に作ったが、実センサ無しで結合試験したい
// 場面全般で使い回せる汎用ツールとして残す。
//
// NAMZ_SENSOR_FAKEビルドフラグでのみ使う想定（本番機のバイナリには含めない）。

#include <cstdlib>

#include "AccelSensor.h"

class FakeSensor : public AccelSensor {
 public:
  bool begin() override { return true; }

  bool read(AccelSample& out) override {
    // IIS3DHHCと同じ0.076mg/LSB換算でZ軸だけ1g相当(≈13158 LSB)に乗せ、
    // 全軸に±20 LSB(≈1.5mg)のノイズを足す。int16の範囲に十分収まる。
    out.x = jitter();
    out.y = jitter();
    out.z = 13158 + jitter();
    return true;
  }

  float scaleMgPerLsb() const override { return 0.076f; }
  // 既存のセンサ種別(0/1/2)と衝突しない値。ダッシュボード側はsensor_typeの
  // 値を検証していないため、未知の値でも壊れない（見た目が変なだけ）。
  uint8_t sensorType() const override { return 255; }
  uint8_t sampleFormat() const override { return 0; /* int16 */ }

 private:
  static int32_t jitter() { return (rand() % 41) - 20; }  // -20..+20 LSB
};
