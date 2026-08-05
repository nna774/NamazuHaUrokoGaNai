# 進捗

新しいものが上。各行の詳細は `log/` の該当ファイルにある。
**このファイルは索引だ。判断の理由は各ログに、現在の結論は各設計ドキュメントにある。**

| 日付 | 何が決まったか | 詳細 |
|---|---|---|
| 2026-08-05 | **TFT画面右下のbacklog表示を「件数+経過時間」(`buf:12 18m`)に拡張する方針。** 件数は`spillCount()`だけでなく`spillCount()+ramQueued()`の合計に修正（従来RAM分が抜けていた）。経過時間はbatch-uplinkに追加した`Uploader::oldestQueuedStartUs()`([batch-uplink#2](https://github.com/nna774/batch-uplink/pull/2)、未マージ)を使う。**`v1.2.0`タグが切られるまでこのブランチはビルドできない**（lib_depsはv1.1.0のまま保留） | [log/2026-08-05-display-backlog-age.md](log/2026-08-05-display-backlog-age.md) |
| 2026-08-05 | **batch-uplinkに`v1.1.0`タグを切ってNamazu側(`lib_deps`/`UPLINK_VERSION`)を追従させ、`main.cpp`に`dropOldestWhenFull=true`を配線した。** その過程で、直前にマージしたPR#4に本来含まれるはずのflash_size修正コミットが1本漏れていた（マージ後にpushしたため）と判明し、cherry-pickで直接masterに修正を入れた。マージ操作は「ボタンを押した時点のHEAD」しか取り込まないという教訓 | [log/2026-08-05-uplink-v1.1.0-and-merge-gap.md](log/2026-08-05-uplink-v1.1.0-and-merge-gap.md) |
| 2026-08-05 | **device2のspill(LittleFS退避)実容量が既定4MB前提のコメント(`config.h`の「90日ぶんの上限目安」)と合っていないと判明。esptool flash_idで実機を物理確認したところ実は16MBあり、`firmware/partitions_adxl355_16mb.csv`（OTA用app0/app1各2MB・spiffs約11.88MB）に書き換えて実機で正常動作（起動・WiFi接続・送信再開）まで確認した。** spill実容量は約19.5分→**約168.8分（約2時間49分）**。**PlatformIOのflash_size上書きキーは`board_build.flash_size`ではなく`board_upload.flash_size`**（前者は黙って無視される。これで一度起動ループを踏んでからの復旧＋原因特定を経ている）。それでも溢れる場合に備え、**batch-uplinkに「spill満杯なら古いデータから捨てる」動作をオプトインで追加する方針**（Electabuzzの既定動作は変えない） | [log/2026-08-05-device2-spill-overflow.md](log/2026-08-05-device2-spill-overflow.md) |
