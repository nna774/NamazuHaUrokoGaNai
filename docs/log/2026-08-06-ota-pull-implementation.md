# HTTPSプル型OTAを実装した

[作戦](2026-08-06-ota-pull-strategy-design.md)と[訂正](2026-08-06-ota-pull-secrets-in-binary.md)
を受けて実装した。**実機での動作確認はまだ**（firmwareビルド全env・
`firmware/test/run.sh`・`pytest lambda/tests tools/tests`(113件)は確認済み）。

## 何を決めたか、なぜそう決めたか

### 秘密情報のNVS化（前提）

旧`secrets.h`のWiFi/HMAC鍵/OTAパスワードをコンパイル時定数からNVS(Preferences)へ
移した。`firmware/lib/DeviceIdentity/`が読み書きを担い、書き込みは
`firmware/src/provision_main.cpp`（`[env:provision]`/`[env:adxl355-provision]`
専用ビルド、main.cppとはbuild_src_filterで排他）が1回だけ行う。`device_id`も
含めて全部NVS化した——env共通の1本のバイナリを複数デバイスで使い回すのが
pull型の前提なので、個体差は1つも残せない。`tools/provision_device.py`は
`secrets-h`を`provision-h`に置き換え、`ingest_url`/`alert_url`に加えて
`api_url`/`ota_base_url`（新規、pull型に要る）もマニフェストから導出するように
した。パーティション表がNVSのオフセットを決めるため、provision専用envも
対象機と同じbase env(esp32dev/adxl355)からextendsして揃えた（16MB機を
esp32dev既定のprovisionで焼くとパーティション表が巻き戻り、spill容量が壊れる）。

### トリガー: 当初案から変更した

作戦時点では[リモート再起動](../remote_restart.md)と同型の「バッチ送信レスポンス
への便乗」を踏襲する案だった。実装に入って、`Uploader::watchResponseHeader`が
単一ヘッダしか監視できず、再起動要求(`X-Namz-Restart`)と共存させるには
batch-uplink（別リポジトリ）の拡張とリリースが要ると分かった。OTAの確認頻度は
バッチ送信頻度（30秒/15秒）と揃える必然性が無いため、**api Lambdaの既存の
読み取り専用エンドポイント`GET /devices/<id>`への独立したGET（5分に1回）**に
変更した。batch-uplink/ingestは無変更で済み、実装がこのリポジトリ内で完結する。
値は一度伝えたら消える一回性のものではなく、デバイスのビルドバージョンと一致する
まで照合し続ける設計（作戦時点の方針を維持）。取得・書き込み失敗時の自然な
リトライにもなる。

### TLS検証: Uploaderより一段厳しくした

`Uploader`は`WiFiClientSecure::setInsecure()`（検証省略、既知のTODO）だが、
OTA取得は取得したものがそのまま実行されるコードになるため、Arduino-ESP32同梱の
ルートCAバンドル(`arduino_esp_crt_bundle_attach`)で正規のTLS検証をするよう
`esp_https_ota`側の設定を分けた。

### sha256突き合わせは見送った

作戦時点では`.sha256`とファーム側で突き合わせる想定だったが、`esp_https_ota`
自身のイメージ検証（マジック・チェックサム）と上記のTLS検証で「正規の
CloudFrontから来た完全なデータ」は担保できると判断し、ファーム側の実装は
省いた。`.sha256`は`tools/publish_ota.sh`が生成し、運用者が手元で目視確認する
用途にとどめた。

### ロールバックは見送った

`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`はbootloaderのsdkconfig変更を伴い、
実機で実際にロールバックが発動するところまで確認しないと安全側に効いているか
判断できない（設定を誤ると起動そのものが壊れうる）。今回のセッションでは実機を
触れないため見送った。

## 何が覆ったか

- 配布物の公開経路は決まっていた（既存CloudFront/S3への相乗り）が、**トリガー
  経路をバッチ送信便乗からapi Lambdaへの独立GETに変更した**（上記）。
- `.sha256`のファーム側検証は当初想定していたが実装しなかった。

## 次に何が可能になったか

- `tools/publish_ota.sh <esp32dev|adxl355>`でビルド〜配布物のアップロードまで
  行える。`tools/request_ota.py request <device_id> <version>`で実際にデバイスへ
  許可を出す。
- 次に実機を触る時、push型（§6）とあわせてpull型の動作確認・ロールバック実装を
  やる。

詳細は[ota.md §7](../ota.md#7-httpsプル型外出先からの更新無人運用向け)を参照。
