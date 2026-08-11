// phase0: ピエゾがGPIO4の保護回路(Rs=47kΩ, Rb=10MΩ, D1/D2=1N60)経由で
// 反応するかを確認するだけの最小スケッチ。詳細は docs/piezo.md 参照。
//
// 書き込み設定: Arduino IDE, ボード = "ESP32C3 Dev Module"
// 確認方法: 書き込み後 Tools > Serial Plotter を開き、円板を指で軽く叩く/
//           机を叩く等で値が動くか見る。

const int kPiezoPin = 4; // GPIO4

void setup() {
  Serial.begin(115200);
  analogSetAttenuation(ADC_11db); // フルスケール(~0-3.3V)を使う
}

void loop() {
  int v = analogRead(kPiezoPin);
  Serial.println(v);
  delay(2);
}
