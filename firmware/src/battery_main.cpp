// UPSバッテリー電圧ADC測定の机上確認用スケッチ。
// docs/ups.md §4/§5、docs/img/ups-battery-adc-wiring.svg の分圧回路
// (10kΩ+10kΩ+Rs1kΩ+C1 0.1µF)を検証機(無印ESP32)へ仮組みし、device2の運用中の
// セルに触れる前にBattery.h(main.cppが実際に使うのと同じコード)の読み値を
// 確認する。WiFi/送信/NVSは一切使わない（main.cppとはsetup()/loop()が排他なので、
// platformio.iniの[env:battery-bringup]でこのファイルだけをビルドする。
// 使い方はfirmware/README.md参照）。
//
// 配線: docs/img/ups-battery-adc-wiring.svg通り。バッテリーはdocs/ups.md §2で
// 交換用に温存している予備の18650(LiFePO4)を使う想定。
//
// 使い方: pio run -e battery-bringup -t upload && pio device monitor
// テスターでNode B(ADCピン=GPIO39直前、C1両端)の電圧を同時に実測し、この出力の
// avg_node_b_mvと突き合わせる。差が大きければ分圧比(config.hのkBatteryDividerRatio、
// 理論値2.0)の較正が要る。raw_mv_1shotの値が読むたびに大きくばらつくなら、
// ソースインピーダンス起因の問題(docs/log/2026-09-28-ups-battery-adc-review-fixes.md)
// を疑う。
#include <Arduino.h>

#include "Battery.h"
#include "config.h"

void setup() {
  Serial.begin(kSerialBaud);
  battery::begin(kPinBatteryAdc);
  Serial.println("# t_ms,raw_mv_1shot,avg_node_b_mv,battery_mv");
}

void loop() {
  static uint32_t next_ms = millis();
  uint32_t now = millis();
  if (static_cast<int32_t>(now - next_ms) < 0) return;
  next_ms += 1000;  // 電池電圧は分〜時間の時定数でしか動かないので1秒毎で十分

  // 単発読み(較正前の生値、ばらつきを目で見る用)と、Battery.h経由の平均読み
  // (本番が実際に使う経路)の両方を出す。
  int oneshot_mv = analogReadMilliVolts(kPinBatteryAdc);
  uint32_t battery_mv = battery::readMillivolts(kPinBatteryAdc, kBatteryDividerRatio);
  // battery_mvは分圧比を掛け戻した後の値なので、割り戻せばNode B(ADCピン直前)の
  // 平均値になる。テスターでNode Bを直接当てる時はこちらと比較する。
  float avg_node_b_mv = battery_mv / kBatteryDividerRatio;

  char line[64];
  int len = snprintf(line, sizeof(line), "%lu,%d,%.1f,%lu\n",
                     static_cast<unsigned long>(now), oneshot_mv, avg_node_b_mv,
                     static_cast<unsigned long>(battery_mv));
  if (len > 0 && Serial.availableForWrite() >= len) {
    Serial.write(reinterpret_cast<const uint8_t*>(line), len);
  }
}
