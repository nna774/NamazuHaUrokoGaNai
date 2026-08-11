#pragma once
// 非校正・生値センサの抽象インターフェイス（ピエゾ等）。
//
// AccelSensorとは別物にしてある。AccelSensorは「x,y,z 3軸・gal換算前提」が
// 型に埋め込まれているが、非校正センサは軸数もgal換算の可否も違う
// （docs/wire_format.md「sensor_type の帯域」、docs/piezo.md §7）。
// 無理に同じ型へ当てはめず、責務を「読んだ生値をそのまま返す」だけに絞る。

#include <cstdint>

class RawSensor {
 public:
  virtual ~RawSensor() = default;

  // 初期化。成功で true。
  virtual bool begin() = 0;

  // 最新の1サンプルを読む。axes() の数だけ out に書く。成功で true。
  virtual bool read(int32_t* out) = 0;

  // サンプルの軸数（ワイヤフォーマットの axes に載る）。
  virtual uint8_t axes() const = 0;

  // ワイヤフォーマットのセンサ種別（128〜249の非校正帯）。
  virtual uint8_t sensorType() const = 0;

  // 生値のフォーマット: 0=int16, 1=int32。
  virtual uint8_t sampleFormat() const = 0;
};
