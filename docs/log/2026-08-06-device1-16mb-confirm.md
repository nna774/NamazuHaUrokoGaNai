# device1の実フラッシュを物理確認し、device2と同じ16MBパーティション構成に揃える

device1（`env:esp32dev`、IIS3DHHC機）をUSB接続し、`esptool.py flash_id`で実チップ容量を
物理確認した。device2と同じくクローンボードだが個体差があり得るため、これまでは
未確認を理由にbase envへの適用を見送っていた
（[2026-08-05-device2-spill-overflow.md](2026-08-05-device2-spill-overflow.md)）。

## 何を決めたか

- **device1も16MBフラッシュと確認できた**（`esptool.py --port /dev/cu.usbserial-5B340453851
  flash_id`: ESP32-D0WDQ6 v1.1、Manufacturer 85 / Device 2018、Detected flash size 16MB。
  MAC `88:13:bf:fd:6f:20`）。device2の物理確認結果（Manufacturer/Deviceとも同一）と揃った。
- パーティション表・`board_upload.flash_size`を`[env:adxl355]`固有設定から
  `[env:esp32dev]`base側へ移した。device2固有のenv(`adxl355`)はbaseをextendsするだけの
  device1固有envと非対称だったので、両機が16MBと分かった今はbase側に寄せるのが自然。
  `adxl355`envは何も上書きせずbaseを継承する。
- パーティションCSVを`partitions_adxl355_16mb.csv`から`partitions_16mb.csv`へリネームした。
  中身はADXL355固有ではなく単なる16MBフラッシュ用のapp0/app1/spiffsサイズ配分なので、
  device1/device2共通の名前が実態に合う（前回ログの「その時に判断する」の回収）。

## なぜそう決めたか

- base側に集約すると、`[env:sensortest]`・`[env:esp32dev-ota]`・`[env:provision]`は
  何も変更せず自動でパーティション表を継承する（`extends = env:esp32dev`のため）。
  provision envのコメントが警告している「16MB機をesp32dev既定のprovisionで焼くと
  パーティション表が巻き戻る」問題も、base自体が16MB前提になったことで構造的に
  発生しなくなった。
- 個別に`[env:esp32dev]`と`[env:adxl355]`の両方に同じ2行を重複させる必要がなくなった。

## 発見された制約

- `esptool`はプロジェクトの`.venv`には入っておらず、`~/.venv/esp/bin/esptool`
  （別途用意されたESP32専用venv）にある。プロジェクト直下の`.venv`はnumpy/scipy/
  platformio用でesptoolは含まれない。

## 次に何が可能になったか

`firmware/platformio.ini`・`partitions_16mb.csv`の設定はこのコミットで揃った。
実機device1への反映（USB接続時にビルド＋書き込みし直し、起動・WiFi接続・送信再開を
確認）はまだ行っていない。device2の時と同様、既存ファーム（4MBパーティション前提）
からの書き換えになるため、実際に焼く際は device2 と同じ手順
（`board_upload.flash_size`を正しく反映したビルドで焼く。`-v`でesptoolコマンド列を
確認する）を踏む。
