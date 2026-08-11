// phase0: ピエゾがGPIO4の保護回路(Rs=47kΩ, Rb=10MΩ, D1/D2=1N60)経由で
// 反応するかを確認するだけの最小スケッチ。詳細は docs/piezo.md 参照。
//
// 確認方法: 書き込み後 `pio device monitor` 等でシリアルを見ながら、
//           円板を指で軽く叩く/机を叩く等で値が動くか見る。
// 生値を毎サンプル出すと流れて読めないため、kWindowMsごとにmin/max/振れ幅
// (peak-to-peak)だけを出す。

#include <Arduino.h>

const int kPiezoPin = 4; // GPIO4
const unsigned long kWindowMs = 100; // この時間内のmin/maxをまとめて出す

void setup() {
  Serial.begin(115200);
  analogSetAttenuation(ADC_11db); // フルスケール(~0-3.3V)を使う
}

void loop() {
  int vmin = 4095;
  int vmax = 0;
  unsigned long windowStart = millis();
  while (millis() - windowStart < kWindowMs) {
    int v = analogRead(kPiezoPin);
    if (v < vmin) vmin = v;
    if (v > vmax) vmax = v;
  }
  Serial.print(vmin);
  Serial.print(",");
  Serial.print(vmax);
  Serial.print(",");
  Serial.println(vmax - vmin); // peak-to-peak
}
