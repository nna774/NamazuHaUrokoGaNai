# 進捗

新しいものが上。各行の詳細は `log/` の該当ファイルにある。
**このファイルは索引だ。判断の理由は各ログに、現在の結論は各設計ドキュメントにある。**

| 日付 | 何が決まったか | 詳細 |
|---|---|---|
| 2026-08-05 | **device2のspill(LittleFS退避)実容量を計算し直し、`config.h`の「90日ぶんの上限目安」コメントが物理パーティション(既定4MB前提)と合っていないと判明。esptool flash_idで実機を物理確認したところ device2 のフラッシュは実は16MBあった。** OTA用app0/app1を現状ビルド(約994KB)に対して十分な各2MBに絞り、残りをspiffsに回す専用パーティション表`firmware/partitions_adxl355_16mb.csv`（`adxl355` envのみ適用）を作った。spill実容量は約19.5分→**約168.8分（約2時間49分）**まで伸びる（`pio run -e adxl355`成功済み）。それでも溢れる場合に備え、**batch-uplinkに「spill満杯なら古いデータから捨てる」動作をオプトインで追加する方針**（Electabuzzの既定動作は変えない） | [log/2026-08-05-device2-spill-overflow.md](log/2026-08-05-device2-spill-overflow.md) |
