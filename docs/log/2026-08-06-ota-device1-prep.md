# device1もpull型OTA対応にし、実機で自己更新を確認した

PR#13（TLS証明書埋め込み・停滞通知）をマージ・watchdog再デプロイした後、
device2に続けてdevice1（IIS3DHHC、`esp32dev` env）もNVS化・pull型OTA対応にした。

## やったこと

1. `tools/provision_device.py provision-h --id 1 --force`でNVS書き込み用
   ヘッダを生成
2. `pio run -e provision -t upload --upload-port /dev/cu.usbserial-5B340453851`
   でNVSへ書き込み。シリアルで`[provision] OK: device 1 written and verified.`
   を確認
3. 続けて`pio run -e esp32dev -t upload`で通常ファームを焼く。起動ログで
   NVS読み込み・WiFi接続（`10.255.255.156`）・センサ初期化・OTA待受
   （`namazu-1.local`）まで正常を確認
4. `api.namazu.dark-kuins.net/devices/1`でバッチ送信が正常再開している
   ことを確認（`batches_total`が伸び続ける）
5. `tools/publish_ota.sh esp32dev`でクリーンな版(`67d83f0`)を公開し、
   `tools/request_ota.py request 1 67d83f0`で許可
6. デバイスが次のバッチ送信時に気づき、安全停止→`HTTPUpdate`（TLS検証込み）
   で取得→書き込み→`ESP.restart()`→新バージョン(`67d83f0`)で起動、
   という一連の流れが**esp32dev envでも**実機で成功した
   （device2の`adxl355` envでは前回確認済み。今回で両方のハードウェア構成
   での動作を確認できた）
7. `tools/request_ota.py cancel 1`で許可を片付け、`api.namazu.dark-kuins.net/devices`
   で両機とも正常稼働に復帰していることを最終確認

## 何を決めたか

- 特に新しい設計判断は無い。device2で確立した手順（NVSプロビジョニング→
  本体ファーム→実際にOTAで一度更新させて検証）をdevice1にもそのまま適用した。

## 次に何が可能になったか

- 本番稼働中の2台とも、手元から`tools/request_ota.py request <id> <version>`
  一発で外出先からの更新ができる状態になった。
- 残るはロールバック（`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`）とpush型OTA
  そのものの実機確認（`unnamed_network_g`に接続した端末から）。どちらも
  次回実機を触る機会に。

詳細は[ota.md §7](../ota.md#7-httpsプル型外出先からの更新無人運用向け)を参照。
