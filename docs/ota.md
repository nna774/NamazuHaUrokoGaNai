# OTA更新

ファームの無線更新。2026-08-06 に §2-A（ArduinoOTA、LAN内push）と
§7（HTTPSプル型、外出先からの更新・無人運用向け）の両方を実装した。
push型はdevice 2へのUSB書き込み・起動・OTAリスナー起動
（`[ota] ready as namazu-2.local`）までは実機で確認できたが、**push本体
（`espota`での転送）は自宅ネットワークの構成により母艦から直接は届かなかった**
（§5「ネットワーク分離」参照）。実装自体の不具合ではなく、試す場所を選ぶ運用上の
制約。pull型は**実機での動作確認はまだ**（firmwareビルド全env・
`firmware/test/run.sh`・`pytest lambda/tests tools/tests` は確認済み）。
関連: [リモート再起動](remote_restart.md)（コマンドラインから再起動要求を送る作戦。
更新後に確認してから確定させる運用の足場になる。今回の実装で使う `flushToSpill()`
はリモート再起動側にも配線し、待ち時間を短縮した）。

## 1. 土台の棚卸し（実装前から整っていたもの）

| 項目 | 状態 |
|------|------|
| パーティション | `esp32dev` 既定の `default.csv` → `app0`/`app1` 各 0x140000 (1.25MB) + `otadata`。**最初からOTA可能な構成** |
| 実装前のファームのサイズ | `firmware.bin` 約 1,025KB（esp32dev / adxl355 ともほぼ同じ）。スロットの **78%**、余裕 約280KB |
| LittleFS | `spiffs` 0x160000 (1.4MB) は app とは別領域。OTAしても `/spill` の退避バッチは消えない |
| 失敗の検知 | watchdog Lambda の欠測通知（既定300秒）が**そのまま安全網になる**。焼き損ねてブートループすればSlackが鳴る |

`platformio.ini` に `board_build.partitions` の指定は無く、ボード既定をそのまま使っている。

## 2. 採用した方式: ArduinoOTA（LAN内からpush）

母艦から `espota`（`pio run -t upload --upload-port ...`）で投げる。デバイス側は
送信タスク（Core0, `uploaderTask`）で `ArduinoOTA.handle()` を回す。測定タスク
（Core1・優先度10）を巻き込まない側に置くのが要点。

HTTPSプル型（`esp_https_ota`。外出先からの更新・無人運用向け）は§7で実装した。
デバイス発信の経路なので、母艦からのpush転送を阻むネットワーク分離（§5）の
影響を受けないという利点もある。

## 3. 使い方

```bash
# デバイスごとのOTAパスワードを引いて焼く（tools/devices.json が単一の真実）
NAMZ_OTA_PASSWORD="$(python tools/provision_device.py ota-password --id 2)" \
    pio run -e "$(python tools/provision_device.py env --id 2)-ota" -t upload \
    --upload-port namazu-2.local
```

`namazu-<id>.local` はデバイスがmDNSで自分に付ける名前（`ArduinoOTA.setHostname()`）。
IPアドレス直指定でもよい（デバイスのTFTに表示されている）。

新規デバイスや既存デバイスの鍵払い出しには `ota_password` フィールドが要る
（`tools/provision_device.py add` が自動生成、`provision-h` でNVS書き込み用の
`secrets_provision.h` に出る。デバイス識別情報のNVS化については§7参照）。

## 4. 安全な停止シーケンス（実装済み）

**フラッシュ書き込み中はキャッシュが無効になり、両コアの命令フェッチが止まる。**
100Hz の `esp_timer` は転送中に確実に取りこぼす。放置すると再起動でRAM上のバッチが
消え、「2xxが返るまでバッチを捨てない」という `Uploader` の不変条件を自分で破る。

対策として batch-uplink に `Uploader::flushToSpill()`（[v1.4.0](https://github.com/nna774/batch-uplink/releases/tag/v1.4.0)、
[PR#4](https://github.com/nna774/batch-uplink/pull/4)）を追加した。RAMキューを
即座に全部LittleFSへ退避するオプトインAPIで、`dropOldestWhenFull`/`watchResponseHeader`
と同じ設計思想（Electabuzz側の挙動は変えない）。

`firmware/src/main.cpp` の `ArduinoOTA.onStart()` コールバックで:

1. `esp_timer_stop(gSampleTimer)` — 測定タイマーを止める
2. `esp_task_wdt_delete(gSamplingTask)` — タイマーが止まると測定タスクは自分で
   `esp_task_wdt_reset()` を呼べなくなるため、転送が終わるまでウォッチドッグの
   監視対象から一時的に外す
3. `gBatchQueue` の残りを `gUploader` へ吸い出し、`flushToSpill()` でLittleFSへ退避

`onProgress()` コールバックで毎回 `esp_task_wdt_reset()` を呼ぶ。ArduinoOTAの転送は
`uploaderTask`（Core0、10秒タイムアウトのタスクウォッチドッグ登録あり）のループ内で
`ArduinoOTA.handle()` 呼び出し1回にブロックして完結するため、これをしないと長い
転送でタスクウォッチドッグが落ちる。

`onEnd()` は不要——ArduinoOTAは成功時に自分で `ESP.restart()` する
（`setRebootOnSuccess()` の既定が `true`）。`onError()` でのみ測定タイマーと
ウォッチドッグ登録を復旧する。

## 5. 実装時の落とし穴（このプロジェクト固有）

- **ロールバックは期待しない。** Arduino core の既定ビルドは
  `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` が入っておらず、新イメージは書けた時点で
  有効扱いになる。自動で前のスロットへ戻ることはない。最後の砦は物理アクセス。
- **パーティションテーブル自体はOTAで変えられない。** app スロットを広げたくなった時
  （`min_spiffs` 等への変更）はUSBで焼き直しになる。実装後のファームは約1,063KB
  （esp32devスロットの81.1%、余裕約242KB）で、ArduinoOTA追加分は約38KB。
  **USBが楽なうちにレイアウトを決めておく**のが安い。
- **env が機種ごとに違う**（IIS3DHHC機は `esp32dev`、ADXL355機は `adxl355`）。OTA用envも
  `esp32dev-ota`/`adxl355-ota` に分けた。env は `python tools/provision_device.py env --id N`
  で引ける。
- **正常なOTAなら欠測通知は鳴らない。** 1MBの転送は数十秒、閾値は300秒。逆に鳴ったら
  本当に失敗しているということ。
- **`Update.begin()` によるパーティション消去は `onStart` コールバックより前に走る。**
  数百ms〜数秒かかりうるが、`onStart`発火前なのでこちらの停止シーケンスはまだ効かず、
  この間の測定タイマー取りこぼしは避けられない（数サンプル〜1秒程度の欠落は許容）。
  タスクウォッチドッグに触れるほど長くなる兆候が実機で見えたら、OTA中だけ
  ウォッチドッグ設定を緩める対応を検討する。
- **`upload_flags` のパスワードは `${sysenv.NAMZ_OTA_PASSWORD}` 経由。** platformio.ini に
  平文で書かない（NVSの秘密情報と同じ扱い）。`upload_port` はデバイスごとに違うので
  `--upload-port` で毎回指定する（platformio.ini には書いていない）。
- **ネットワーク分離で母艦から push が届かないことがある。** device 2 は
  `unnamed_network_g`（`10.255.255.0/24`）に居るが、母艦のMacは別セグメント
  （`10.8.30.0/24`）。2026-08-06に実際に試したところ:
  - `ping 10.255.255.1`（デバイス側ゲートウェイ）は通る（ttl=63、1ホップ挟んでルーティング
    はされている）
  - `namazu-2.local` のmDNS解決は失敗（`Host ... Not Found`）
  - IP直指定でも `espota` のUDP招待（ポート3232）に**無応答**（`No response from the ESP`）

  ICMPは通るのにUDP往復が通らないのは、SSID名の `_g`（ゲスト回線らしき命名）が示す
  とおり**VLAN間のクライアント分離**が疑わしい（デバイスの発信＝AWSへのHTTPS送信は
  素通り、他ホストからの着信だけ塞がれる構成）。デバイス側のOTAサーバ自体は起動ログ
  で稼働を確認済みなので、ファーム実装の問題ではない。
  **試す時は `unnamed_network_g` に実際に接続した端末（スマホ・同SSID上のPC）から
  `espota` を叩くか、ルータ/APの当該SSID設定でクライアント分離を確認すること。**

## 6. 未着手

- **push OTA転送そのものの実機確認**（次回、`unnamed_network_g` に接続した端末から。§5参照）。
- **pull型OTAの実機確認**（次回訪問時。手元のWiFiから外れた環境で試すのが理想）。
- HTTPSプル型のロールバック（§7「今回は見送った」参照）。

## 7. HTTPSプル型（外出先からの更新・無人運用向け）

2026-08-06に実装した。**実機での動作確認はまだ**（firmwareビルド全env・
`firmware/test/run.sh`・`pytest lambda/tests tools/tests`は確認済み）。前提:
LAN内push（§2）は運用者が対象デバイスと同じLANにいる必要がある。外出先からの
更新・無人運用にはデバイス自身がHTTPSで取得（pull）する方式が要る。

### 前提として先に片付けた: バイナリの秘密情報の分離（NVS化）

当初「`ota/<env>/<version>.bin`を1本、CloudFrontで公開する」という配布物の作戦を
立てたが、**現状のファーム構成のままでは成立しない**と判明した。

旧`secrets.h`（`tools/provision_device.py`が生成）は、WiFi SSID/パスワード・
デバイス固有のHMAC鍵（バッチ投稿の認証に使う）・ArduinoOTA認証パスワードを
`static constexpr const char*`の文字列リテラルとして持っていた。コンパイラは
これを暗号化も難読化もしないので、焼いた`firmware.bin`には平文のまま入る。
push型（LAN内espota）は送り返す相手が秘密の持ち主自身なので問題にならなかったが、
pull型で「envごとに1本を不特定多数が読めるURLに置く」設計は、公開した瞬間その
1台の家WiFiとなりすまし投稿の鍵を世界に漏らすことになる。

対策としてデバイス識別情報・秘密・エンドポイントURLをコンパイル時定数から
**NVS(Preferences)**へ移した（`firmware/lib/DeviceIdentity/`）。OTAはapp
パーティションのみを書き換えNVSには触らないため、identity/secretsはOTAを
またいで保持される。書き込みは初回USB書き込み時、専用の`[env:provision]`/
`[env:adxl355-provision]`ビルド（`firmware/src/provision_main.cpp`）で1回だけ
行う。通常のfirmware(`main.cpp`)は起動時にNVSから読み、空なら（未
プロビジョニング）**測定・送信を一切開始せず起動時ログを出し続けて停止する**
（不定な状態で動かさない）。

```bash
python tools/provision_device.py provision-h --id N        # secrets_provision.h を生成
pio run -e provision -t upload --upload-port <USBポート>    # NVSへ書く（ADXL355機は adxl355-provision）
pio run -e esp32dev -t upload --upload-port <USBポート>     # 続けて通常のfirmwareを焼く
```

これで`ota/<env>/<version>.bin`は本当にenv共通の中身になり、公開して問題なく
なった。旧`secrets.h`/`secrets.h.example`は削除し、`tools/provision_device.py`の
`secrets-h`コマンドは`provision-h`に置き換えた。

### トリガー: リモート再起動と同じ「バッチ送信レスポンスへの便乗」（自律ポーリングは不採用）

配布物（S3/CloudFront上のbin）の書き込み権限が万一侵害された場合、無人運用中の
全機へ運用者の操作なしにコードが流し込める経路になるとpushより一段階ブラスト
半径が大きい。そこで「運用者が明示的に許可した時だけ取得する」設計にした。

作戦時点の方針どおり、[リモート再起動](remote_restart.md)と同じ「バッチ送信
レスポンスへの便乗」を踏襲した。

- 手元: `tools/request_ota.py request <device_id> <version>` で `namazu-devices`
  DynamoDBテーブルに`pending_ota_version`（文字列）を直接セットする
  （`request_restart.py`と同型のCLI。`cancel`/`list`もある）。
- ingest `_handle_batch` が `pending_ota_version` を見て、あればレスポンス
  ヘッダ `X-Namz-Ota-Version: <version>` を返す。
- **リモート再起動要求と違い、返した直後にクリアしない。** 再起動要求は
  「一度実行したら意味を失うイベント」だが、OTAターゲットは「あるべき状態」
  なので照合し続けてよい。デバイスは埋め込みビルドバージョン
  (`NAMZ_FW_VERSION`)と一致するまで、バッチ送信のたびに同じ指示を受け取り
  続ける。これは同時に**自然なリトライ機構**になる——ダウンロード失敗や
  書き込み失敗で古いバージョンのまま再起動しても、次のバッチ送信で再び
  気づいて再試行する。

実装当初は`Uploader::watchResponseHeader`が**単一ヘッダしか監視できず**、
再起動要求(`X-Namz-Restart`)と共存させられないという制約にぶつかった。ここで
batch-uplinkに触れずに済ませようとapi Lambdaへの独立GETに設計変更したが、
これは「うまくいかなかったら別設計に変える」を無断でやってしまったやり直し
——**batch-uplinkの拡張は最初から許容範囲**だった。
[batch-uplink v1.5.0](https://github.com/nna774/batch-uplink/releases/tag/v1.5.0)
で`Uploader`を複数ヘッダ監視に対応させ（`watchResponseHeaders`配列 + `lastResponseHeaderValue(name)`。
`kMaxWatchedHeaders=4`まで）、当初案どおりバッチ送信のたびに両方のヘッダを
一緒に読む設計に作り直した。`firmware/platformio.ini`の`lib_deps`と
`terraform/build_lambda.sh`の`UPLINK_VERSION`をv1.5.0へ揃えて上げてある
（CLAUDE.mdの不変条件）。

### 配布物: 既存CloudFrontに相乗り

新規ドメイン/ACM証明書を作らず、ダッシュボード配信で使っている既存の
S3バケット（`aws_s3_bucket_policy`が`${bucket.arn}/*`とバケット全体を対象に
しているため、追加の権限設定は不要）+ CloudFrontに`ota/`プレフィックスで
相乗りする。ファイル名にバージョン(gitの短縮hash)を含むため公開後に内容が
変わることはなく、CloudFrontの invalidation も不要。

```
ota/<env>/<version>.bin      # 例: ota/esp32dev/a1b2c3d.bin
ota/<env>/<version>.sha256   # 運用者が手元で照合する用（ファームは未検証。後述）
```

`env`は`esp32dev`/`adxl355`（センサ・ボードの組。espota用の`-ota` envは
アップロード方式が違うだけで中身は同じビルドなのでここには出てこない）。
`tools/publish_ota.sh esp32dev`でビルド〜アップロードまで行う（作業ツリーが
汚れていたら既定で拒否、`--allow-dirty`で強制可）。

### バージョン識別: ビルド時にgit短縮hashを埋め込む

`firmware/get_fw_version.py`（extra_script）が`git rev-parse --short HEAD`を
`NAMZ_FW_VERSION`へ、env名から`NAMZ_OTA_ENV`（esp32dev/adxl355）を注入する。
作業ツリーが汚れていたら`-dirty`サフィックスを付け、未コミット状態を配布版として
掴む事故に気付けるようにする。起動シリアルログにも出す
（[memo.md](../memo.md)の残タスク「起動時のログにバージョン/hash」を解消）。

### ダウンロード: HTTPUpdate + push型と同じ安全停止シーケンス

- 更新対象を見つけたら、push型（§4）と同じ手順でRAMキューを退避する
  （`pauseSamplingForOta()`に共通化: 測定タイマー停止→測定タスクをWDT監視から
  外す→`flushToSpill()`）。
- 取得はArduino-ESP32の`HTTPUpdate`（`httpUpdate.update(client, url)`。内部は
  `WiFiClientSecure`+`HTTPClient`、書き込みはArduinoOTAと同じ`Update.h`）。
  `onProgress`コールバックで毎回`esp_task_wdt_reset()`を呼ぶ（ArduinoOTAの
  `onProgress`と同じ役割。ブロッキングAPIそのままだと進行中にWDTを養えない）。
  `rebootOnUpdate(false)`にして再起動はこちらで制御する。
- 成功なら`ESP.restart()`。失敗系は測定タイマー・WDT登録を復旧して測定続行
  （push型`onError`と同じ）し、1分のバックオフを置いて次回のバッチ送信時の
  チェックでリトライする（後述、実機で踏んだ不具合）。

**TLS検証は実機で2段階の失敗を踏んでからルートCA埋め込みに落ち着いた**
（2026-08-06、device2実機）:

1. 当初はESP-IDFの低レベルAPI(`esp_https_ota_begin`/`perform`/`finish` +
   `esp_http_client_config_t.crt_bundle_attach = arduino_esp_crt_bundle_attach`)
   でルートCAバンドル検証する設計だったが、実機で常に
   `Failed to attach bundle`となりTLSハンドシェイクが失敗した。
2. Arduino-ESP32の`HTTPUpdate`（`WiFiClientSecure`+`HTTPClient`経由）に
   切り替え、`setInsecure()`を呼ばない既定CAバンドル検証を試したが、これも
   `start_ssl_client: -1`で同様に失敗した。PlatformIOのArduinoフレームワーク
   ビルドでは、既定CAバンドルの実体を生成するesp-idf側のcmakeステップが
   走らず、空のままリンクされていると見られる——低レベルAPI・
   `WiFiClientSecure`のどちらの経路でも「既定のバンドル任せ」は機能しない。
3. `namazu.dark-kuins.net`実機で証明書チェーンを確認
   (`openssl s_client -showcerts`)し、`namazu.dark-kuins.net` ->
   `Amazon RSA 2048 M01` -> `Amazon Root CA 1`と判明。ルートCAを1本だけ
   `firmware/certs/amazon_root_ca1.pem`として同梱し、`platformio.ini`の
   `board_build.embed_txtfiles`でリンク、`WiFiClientSecure::setCACert()`で
   明示検証する方式にしたところ、実機でTLSハンドシェイクが通り、取得〜
   書き込み〜再起動〜新バージョンでの起動まで成功した。
   これは`Uploader`の`setInsecure()`割り切りより厳格な正規のTLS検証になる。
   出典は https://www.amazontrust.com/repository/AmazonRootCA1.pem
   （有効期限2038-01-17。CAがローテーションされたら要更新）。

**`.sha256`との突き合わせはファーム側では実装していない**（`HTTPUpdate`
（`Update.h`）自身がESP32イメージのマジック・チェックサムを検証するのと、
上記のTLS検証で「正規のCloudFrontから来た完全なデータ」であることは担保
できる。バージョン文字列を取り違えて誤った版を公開する運用ミス対策としては、
`.sha256`は`publish_ota.sh`が生成し運用者が手元で目視確認する用途に留めた）。

### 実機で踏んだ不具合: 失敗時の高頻度リトライで測定が止まった

トリガー(`X-Namz-Ota-Version`)は`Uploader`がキャッシュする最終成功レスポンスの
値で、失敗直後は同じ値のまま変わらない。当初の実装はこの値を見て「不一致なら
即座に取得を試みる」だけで、失敗時のバックオフが無かった。結果、
`uploaderTask`のループ周期（約50ms＋ネットワーク待ち）ごとに取得を再試行する
高頻度リトライになり、そのたびに`pauseSamplingForOta()`で測定タイマーが
止まったまま実質戻らず、**実測が止まった**（device2実機で欠測を招いた。原因は
上記1のTLS失敗）。1分のバックオフ（`checkAndPerformPullOta`内の
`static uint32_t sNextAttemptMs`）を追加して解消した。

### 停滞の検知: watchdog Lambdaに通知を追加

`pending_ota_version`は一回性ではなく「あるべき状態」として持ち続けるため、
証明書検証失敗のような問題が起きてもデバイスは（測定を止めずに）黙って
バックオフ・リトライを繰り返すだけになる——手元で`request_ota.py list`を
覗きに行かない限り気づけない。実機でTLS検証の不具合を2回連続で踏んだ実体験
から、**要求してから`NAMZ_OTA_STUCK_AFTER_S`(既定1800秒=30分)を超えて
解消しなければwatchdog LambdaがSlack通知する**ようにした
（`lambda/common/ota_watch.py`の`evaluate_ota_stuck`、
`NAMZ_OTA_STUCK_RENOTIFY_S`(既定1日)間隔で再送）。原因（証明書検証失敗か
ネットワーク不調か配布物の取り違えか）は問わず、「何かがおかしい」ことだけを
拾う。`tools/request_ota.py request`が`pending_ota_requested_at_us`を、
`cancel`が`ota_stuck_notified_at_us`含め一式を消す。

### ロールバック: 今回は見送った

push型（§5）で書いた「ロールバックは期待しない、最後の砦は物理アクセス」は
pull型でも変わっていない。無人トリガーで焼き損じた場合に自動で前スロットへ
戻れる`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`は本来pull型でこそ価値が出るが、
これはbootloaderのsdkconfig変更を伴い、**実際にロールバックが発動する
ところまで確認しないと安全側に効いているか判断できない**（設定を間違えると
起動そのものが壊れうる）。今回は他の実機不具合（TLS・リトライ）の修正で
手一杯になったため見送った。次に実機を触る機会に、push型の実機確認
（§6の残タスク）と合わせて検討する。

### 未決事項・既知の割り切り

- **ロールバック未実装**（上記）。実機確認のタイミングでやる。
- **段階的ロールアウト**（1台だけ先に上げて様子見）は`pending_ota_version`を
  デバイス単位で持つ設計なので自然に表現できる（`request_ota.py`はdevice_id
  必須）。運用手順としては既に可能。
- 16MB機（`partitions_adxl355_16mb.csv`）のパーティションサイズ差はビルドenv差に
  吸収されるので、pull型固有の対応は不要（push型と同じ扱い）。NVSプロビジョニング
  も対象機と同じbase env(`adxl355-provision`)からextendsしてパーティション表を
  揃えている（provision専用ビルドで誤って4MB既定に巻き戻すとspill容量が壊れる
  ため）。
- **watchdogの停滞検知は「解消していない」ことしか分からない。** サーバは
  デバイスの現在バージョンを知らないので、原因の切り分けは実機のシリアル
  ログを見に行く必要がある（ota.md §7 未決事項1と同根）。
