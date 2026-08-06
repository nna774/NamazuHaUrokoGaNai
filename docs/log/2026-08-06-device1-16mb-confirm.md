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

- **実機device1への反映まで完了した。** USBで新パーティション構成のビルド
  （version `a93433a`）を書き込み、起動・WiFi接続・送信再開・パーティション表の
  物理読み出し確認（`esptool read_flash 0x8000` → `gen_esp32part.py`でapp0/app1が
  各2MB・spiffsが12160KBと確認）まで完了した。

## 途中で踏んだ事故: pull型OTAによる自動差し戻し

USB書き込み直後、device1が一度は`a93433a`でオンライン化したが、**直後に自動で
古い版（`c64f379`）へ差し戻った。** 原因はDynamoDB `namazu-devices`の
`pending_ota_version`が、当日の別セッションで行ったOTA検証（`c64f379`）の値の
まま残っていたこと。`main.cpp`の`checkAndPerformPullOta()`は
`target == kFwVersion`でない限り無条件にpull-OTAを試みる設計
（[docs/ota.md](../ota.md) §7の「値は消費しない」方針どおり）なので、USBで
`a93433a`に書き換えた直後、device1自身が「サーバの要求(`c64f379`)と自分の版が
違う」と検知し、勝手に`c64f379`を取得・書き込み・再起動した。

**復旧はUSBの焼き直しではなく、正規のOTA経路で行った。** `tools/publish_ota.sh
esp32dev`で`a93433a`をS3(`ota/esp32dev/a93433a.bin`)へ公開し、
`tools/request_ota.py request 1 a93433a`で許可を出し、device1が次のバッチ送信時に
自分でpullするのを待った（約3分で収束、`fw_version`=`pending_ota_version`=
`a93433a`で安定）。パーティション表自体はOTAでは書き換わらない
（アプリスロットのみ更新）ため、USB時点で確定済みの16MB構成はそのまま活きている。

## 発見された制約

- `esptool`はプロジェクトの`.venv`には入っておらず、`~/.venv/esp/bin/esptool`
  （別途用意されたESP32専用venv）にある。プロジェクト直下の`.venv`はnumpy/scipy/
  platformio用でesptoolは含まれない。
- **`pending_ota_version`を「消費しない」設計（取得失敗時の自然なリトライのため）
  には、意図しない副作用がある。** 一致を一度確認した後もサーバ側の値が残り続ける
  ため、後から意図的にUSBで別バージョンへ焼き直すと、device側が「要求と食い違う」
  と判断して勝手に元のバージョンへ戻す。今回はUSB直後にこれを踏んだ。
- ユーザーから、ingestが受信したバッチの`fw_version`と`pending_ota_version`が
  一致した時点でサーバ側が`pending_ota_version`を自動クリアする案が出た
  （「取得できるまでリトライ」は維持しつつ「達成後は解放する」形にできる）。
  今回は実装を見送り、正規のOTA経路で回避して完了させた。**次にOTA周りを触る時の
  検討候補として`docs/ota.md`の未決事項に残す。**

## 次に何が可能になったか

`firmware/platformio.ini`・`partitions_16mb.csv`の設定、および実機device1
（`a93433a`、16MBパーティション構成）ともに本番復帰済み。device2と合わせて
両機とも16MBフラッシュを使い切る構成で稼働している。
