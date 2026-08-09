# IIS3DHHC(1号機)の内蔵温度センサを有効化した

## 何を決めたか

`firmware/lib/Iis3dhhc/`が`AccelSensor::readTemperatureRaw()`を実装し、
1号機（IIS3DHHC）もADXL355（2号機）と同じ温度トレイラー・API・ダッシュボードの
パイプラインに乗るようにした。

## なぜ

1号機を2号機と同じブロックへ「ブレッドボードごと剛結」する据え付け案を検討中、
「1号機は温度が分からないから2号機のセンサ読みで代用できないか」という話になった。
しかしこの貼り方だとセンサがESP32/WiFiの発熱源のすぐ隣に居座る一方、2号機は
リボンケーブルでセンサを本体から意図的に離してある（[adxl355.md §4.1](../adxl355.md)）。
つまり自己発熱の乗り方が機体ごとに非対称で、2号機の温度では1号機のセンサ直近の
発熱を代弁できない。

「IIS3DHHCは温度センサを持たない」という前提（`dashboard/app.js`のコメントに
そう書かれていた）で外付けセンサが要ると判断しかけたが、STの公式レジスタ定義
（[iis3dhhc-pid](https://github.com/STMicroelectronics/iis3dhhc-pid)の
`iis3dhhc_reg.c`）を見たところ前提が誤りだった。`OUT_TEMP_L`(0x25)/`OUT_TEMP_H`(0x26)
の16bitレジスタが実在し、`iis3dhhc_from_lsb_to_celsius()`と同じ換算式
（℃ = raw/16 + 25）が使える。

## 何が覆ったか

- 「IIS3DHHCは温度非対応」という前提そのもの（コードのコメントに残っていた誤り）。
- 外付け温度センサが必要という判断（不要になった）。

## 実装

- `firmware/lib/Iis3dhhc/Iis3dhhc.{h,cpp}`: `readTemperatureRaw()`を追加。
  レジスタ読み出しは既存の`read()`（0x28から6byte、IF_ADD_INC前提）と同じ流儀。
  `main.cpp`側は元から`AccelSensor`インタフェース経由の汎用呼び出し
  （`if (gSensor.readTemperatureRaw(temp))`）なので無改修で乗った。
- `lambda/common/wire.py`: `iis3dhhc_temp_c()`を追加し、`temp_c_for()`の分岐に足した。
  ファームはOUT_TEMPの符号付き16bitをビット列のままuint16トレイラーに乗せるので、
  Lambda側で符号拡張してから換算する。
- `dashboard/app.js`: デバイス詳細ページの温度セクション表示条件
  （`hasTemp = d.sensor === 'ADXL355'`）にIIS3DHHCを追加。
- テスト: `lambda/tests/test_wire.py`・`test_api_devices.py`の
  「IIS3DHHCは温度非対応」を前提にしたテストを、実際の換算値を検証する形に直した。

## 次に何が可能になったか

1号機を（雑な貼り方でも）剛結すれば、その温度トレンドが取れるようになった。
自己発熱由来のドリフトかどうかを2号機の温度と比較して切り分けられる
（[device_overlay.md](../device_overlay.md)の較正議論の続き）。

pio run(esp32dev)成功・`test/run.sh`成功・pytest 109件通過。
**実機書き込み・OTA配信・本番デプロイはまだ。**
