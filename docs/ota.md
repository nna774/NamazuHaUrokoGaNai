# OTA更新

ファームの無線更新。**現在の方式はHTTPSプル型（デバイス自身が取得しにいく）のみ。**

2026-08-06にLAN内push型（ArduinoOTA、母艦から`espota`で焼く）とHTTPSプル型を
両方実装したが、push型は自宅ネットワークのVLAN分離で母艦からの転送がデバイスに
一度も届かず（§3「実装時の落とし穴」参照）、実用にならないまま放置されていた。
2026-08-10、実際に使っていない機能を削るとDRAM/Flashが空くかという調査（震度計算の
静的バッファ削減と同じ流れ）の一環でpush型一式を撤去した。詳細は
[log/2026-08-10-drop-lan-push-ota.md](log/2026-08-10-drop-lan-push-ota.md)。

pull型は2026-08-06にdevice1(esp32dev)・device2(adxl355)両方で実際に自己更新
（旧バージョン→再ビルド版）まで成功している。2026-08-12、device3(ピエゾ、
`piezo`env)にも同じロジックを移植した（[log/2026-08-12-piezo-ota-and-observability-headers.md](log/2026-08-12-piezo-ota-and-observability-headers.md)）。
シングルコア(ESP32-C3)でも成立する設計だが、**実機投入・実OTA転送確認は
まだ**（コード実装・ビルド確認・パーティション確認のみ完了）。
関連: [リモート再起動](remote_restart.md)（コマンドラインから再起動要求を送る作戦。
`flushToSpill()`を共有する）。

## 0. クイックリファレンス（実際に配る時はここだけ読めばいい）

**きれいなworktree（masterから素朴に切った、untrackedファイルも変更も無い状態）で
ビルドすること。** リポジトリ直下に`memo.md`等の無関係なuntrackedファイルが
あるだけでも`git status --porcelain`がdirtyと判定し、配布版数が`<hash>-dirty`
になる（動作は変わらないが、後から見た時に「本当にこの内容か」を素直に信じられ
なくなる。実際に2026-08-11、手元の作業ディレクトリのスクラッチファイルのせいで
`--allow-dirty`を使う羽目になった）。`EnterWorktree`等で新しいworktreeを切れば
untrackedファイルを一切引き継がないので、`--allow-dirty`無しで素直に通る。

```bash
# 1. きれいなworktreeで確認（念のため）
git status --short   # 何も出なければOK

# 2. ビルド・S3公開（gitの短縮hashがそのまま配布バージョンになる）
tools/publish_ota.sh esp32dev   # 1号機(IIS3DHHC)向け。2号機(ADXL355)なら adxl355、3号機(ピエゾ)なら piezo
#   最後に「python tools/request_ota.py request <device_id> <version>」が出力される

# 3. 対象デバイスに許可を出す(device_idはtools/devices.json参照。1号機=1・2号機=2・3号機=3)
NAMZ_DEVICES_TABLE=namazu-devices .venv/bin/python tools/request_ota.py request 1 <version> --yes
#   --yes を付けないと確認プロンプトで止まる(非対話実行では必須)

# 4. 反映待ち・確認（バッチ送信のたびに照合するので数十秒〜数分かかる）
NAMZ_DEVICES_TABLE=namazu-devices .venv/bin/python tools/request_ota.py list
curl -s https://api.namazu.dark-kuins.net/devices/1 | python3 -m json.tool | grep fw_version
#   fw_versionが指定バージョンに変われば成功

# 取り消したい時
NAMZ_DEVICES_TABLE=namazu-devices .venv/bin/python tools/request_ota.py cancel 1
```

設計の経緯・トリガーの仕組み・安全な停止シーケンス等は以下の本編参照。

## 1. 土台の棚卸し（実装前から整っていたもの）

| 項目 | 状態 |
|------|------|
| パーティション | `esp32dev` 既定の `default.csv` → `app0`/`app1` 各 0x140000 (1.25MB) + `otadata`。**最初からOTA可能な構成** |
| 実装前のファームのサイズ | `firmware.bin` 約 1,025KB（esp32dev / adxl355 ともほぼ同じ）。スロットの **78%**、余裕 約280KB |
| LittleFS | `spiffs` 0x160000 (1.4MB) は app とは別領域。OTAしても `/spill` の退避バッチは消えない |
| 失敗の検知 | watchdog Lambda の欠測通知（既定300秒）が**そのまま安全網になる**。焼き損ねてブートループすればSlackが鳴る |

`platformio.ini` に `board_build.partitions` の指定は無く、ボード既定をそのまま使っている。

## 2. 採用した方式: HTTPSプル型（外出先からの更新・無人運用向け）

2026-08-06に実装。デバイスがバッチ送信のたびにサーバへ更新有無を問い合わせ
（後述のトリガー）、あれば`HTTPUpdate`で取得・書き込みする。運用者が対象デバイスと
同じLANにいる必要が無いのが利点で、デバイス発信の経路なので後述のネットワーク
分離の影響も受けない。

### 使い方

```bash
# ビルド〜CloudFrontへの配布
tools/publish_ota.sh esp32dev            # ADXL355機は adxl355

# 対象デバイスに更新を許可する（tools/devices.json が単一の真実）
python tools/provision_device.py env --id 2   # 焼くべきenv名の確認
python tools/request_ota.py request 2 <version>
python tools/request_ota.py list              # 状態確認
python tools/request_ota.py cancel 2          # 取り消し
```

新規デバイスや既存デバイスの識別情報払い出しには`tools/provision_device.py provision-h`
（NVS書き込み用の`secrets_provision.h`を生成）を使う。デバイス識別情報のNVS化に
ついては§2.1参照。

### 2.1 前提として先に片付けた: バイナリの秘密情報の分離（NVS化）

当初「`ota/<env>/<version>.bin`を1本、CloudFrontで公開する」という配布物の作戦を
立てたが、**現状のファーム構成のままでは成立しない**と判明した。

旧`secrets.h`（`tools/provision_device.py`が生成）は、WiFi SSID/パスワード・
デバイス固有のHMAC鍵（バッチ投稿の認証に使う）を`static constexpr const char*`の
文字列リテラルとして持っていた。コンパイラはこれを暗号化も難読化もしないので、
焼いた`firmware.bin`には平文のまま入る。pull型で「envごとに1本を不特定多数が
読めるURLに置く」設計は、公開した瞬間その1台の家WiFiとなりすまし投稿の鍵を
世界に漏らすことになる。

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

### 2.2 トリガー: リモート再起動と同じ「バッチ送信レスポンスへの便乗」（自律ポーリングは不採用）

配布物（S3/CloudFront上のbin）の書き込み権限が万一侵害された場合、無人運用中の
全機へ運用者の操作なしにコードが流し込める経路になると一段階ブラスト半径が
大きい。そこで「運用者が明示的に許可した時だけ取得する」設計にした。

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

`Uploader::watchResponseHeaders`（複数ヘッダ監視、`kMaxWatchedHeaders=4`まで）で
再起動要求(`X-Namz-Restart`)と共存させている（[batch-uplink v1.5.0](https://github.com/nna774/batch-uplink/releases/tag/v1.5.0)）。
`firmware/platformio.ini`の`lib_deps`と`terraform/build_lambda.sh`の
`UPLINK_VERSION`をこのタグへ揃えて上げてある（CLAUDE.mdの不変条件）。

### 2.3 配布物: 既存CloudFrontに相乗り

新規ドメイン/ACM証明書を作らず、ダッシュボード配信で使っている既存の
S3バケット（`aws_s3_bucket_policy`が`${bucket.arn}/*`とバケット全体を対象に
しているため、追加の権限設定は不要）+ CloudFrontに`ota/`プレフィックスで
相乗りする。ファイル名にバージョン(gitの短縮hash)を含むため公開後に内容が
変わることはなく、CloudFrontの invalidation も不要。

```
ota/<env>/<version>.bin      # 例: ota/esp32dev/a1b2c3d.bin
ota/<env>/<version>.sha256   # 運用者が手元で照合する用（ファームは未検証。後述）
```

`env`は`esp32dev`/`adxl355`（センサ・ボードの組）。`tools/publish_ota.sh esp32dev`
でビルド〜アップロードまで行う（作業ツリーが汚れていたら既定で拒否、
`--allow-dirty`で強制可）。

### 2.4 バージョン識別: ビルド時にgit短縮hashを埋め込む

`firmware/get_fw_version.py`（extra_script）が`git rev-parse --short HEAD`を
`NAMZ_FW_VERSION`へ、env名から`NAMZ_OTA_ENV`（esp32dev/adxl355）を注入する。
作業ツリーが汚れていたら`-dirty`サフィックスを付け、未コミット状態を配布版として
掴む事故に気付けるようにする。起動シリアルログにも出す。

### 2.5 安全な停止シーケンス

**フラッシュ書き込み中はキャッシュが無効になり、両コアの命令フェッチが止まる。**
100Hz の `esp_timer` は転送中に確実に取りこぼす。放置すると再起動でRAM上のバッチが
消え、「2xxが返るまでバッチを捨てない」という `Uploader` の不変条件を自分で破る。

対策として batch-uplink に `Uploader::flushToSpill()`（[v1.4.0](https://github.com/nna774/batch-uplink/releases/tag/v1.4.0)、
[PR#4](https://github.com/nna774/batch-uplink/pull/4)）を追加した。RAMキューを
即座に全部LittleFSへ退避するオプトインAPIで、`dropOldestWhenFull`/`watchResponseHeader`
と同じ設計思想（Electabuzz側の挙動は変えない）。

`firmware/src/main.cpp` の `checkAndPerformPullOta()` が更新対象を見つけた時点で:

1. `pauseSamplingForOta()` を呼ぶ:
   1. `esp_timer_stop(gSampleTimer)` — 測定タイマーを止める
   2. `esp_task_wdt_delete(gSamplingTask)` — タイマーが止まると測定タスクは
      自分で`esp_task_wdt_reset()`を呼べなくなるため、転送が終わるまで
      ウォッチドッグの監視対象から一時的に外す
   3. `gBatchQueue` の残りを `gUploader` へ吸い出し、`flushToSpill()` でLittleFSへ退避
2. 取得はArduino-ESP32の`HTTPUpdate`（`httpUpdate.update(client, url)`。内部は
   `WiFiClientSecure`+`HTTPClient`、書き込みは`Update.h`）。`onProgress`
   コールバックで毎回`esp_task_wdt_reset()`を呼ぶ（ブロッキングAPIそのままだと
   進行中にWDTを養えない）。`rebootOnUpdate(false)`にして再起動はこちらで制御する。
3. 成功なら`ESP.restart()`。失敗系は`resumeSamplingAfterOtaFailure()`で測定
   タイマー・WDT登録を復旧して測定続行し、1分のバックオフを置いて次回のバッチ
   送信時のチェックでリトライする（後述、実機で踏んだ不具合）。

**TFT表示もこのシーケンスに連動させている。** 測定タイマーが止まると
`gDispIntensity` 等は最後の値のまま凍るため、震度画面を出し続けると
「更新中で止まっている」のか「地震計が本当に固まった」のか目視で区別できない。
`pauseSamplingForOta()`で立てる`gOtaInProgress`フラグを`loop()`が見て、震度画面の
代わりに`Display::renderOtaUpdating()`（紫背景 + "OTA UPDATING"）を出す。日時だけは
`loop()`側で毎フレーム計算し続けるので、更新中画面でもフリーズ検知の役目は保てる。

### 2.6 TLS検証

**実機で2段階の失敗を踏んでからルートCA埋め込みに落ち着いた**（2026-08-06、device2実機）:

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

### 2.7 実機で踏んだ不具合: 失敗時の高頻度リトライで測定が止まった

トリガー(`X-Namz-Ota-Version`)は`Uploader`がキャッシュする最終成功レスポンスの
値で、失敗直後は同じ値のまま変わらない。当初の実装はこの値を見て「不一致なら
即座に取得を試みる」だけで、失敗時のバックオフが無かった。結果、
`uploaderTask`のループ周期（約50ms＋ネットワーク待ち）ごとに取得を再試行する
高頻度リトライになり、そのたびに`pauseSamplingForOta()`で測定タイマーが
止まったまま実質戻らず、**実測が止まった**（device2実機で欠測を招いた。原因は
上記2.6の1のTLS失敗）。1分のバックオフ（`checkAndPerformPullOta`内の
`static uint32_t sNextAttemptMs`）を追加して解消した。

### 2.8 停滞の検知: watchdog Lambdaに通知を追加

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

### 2.9 ロールバック: 見送ったまま

「ロールバックは期待しない、最後の砦は物理アクセス」という割り切りは変わって
いない。Arduino core の既定ビルドは`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`が
入っておらず、新イメージは書けた時点で有効扱いになる。自動で前のスロットへ
戻ることはない。無人トリガーで焼き損じた場合に自動で前スロットへ戻れる
この設定は本来pull型でこそ価値が出るが、bootloaderのsdkconfig変更を伴い、
**実際にロールバックが発動するところまで確認しないと安全側に効いているか
判断できない**（設定を間違えると起動そのものが壊れうる）ため見送っている。

## 3. 過去に検討したLAN内push（ArduinoOTA）と、撤去した理由

2026-08-06に`ArduinoOTA`（母艦から`espota`で焼く）も実装し、device 2への
USB書き込み・起動・OTAリスナー起動（`namazu-2.local`のmDNS広告）までは実機で
確認できたが、**push本体（`espota`での転送）は自宅ネットワークの構成により
母艦から一度も届かなかった**:

- `ping 10.255.255.1`（デバイス側ゲートウェイ）は通る（ttl=63、1ホップ挟んで
  ルーティングはされている）
- `namazu-2.local` のmDNS解決は失敗（`Host ... Not Found`）
- IP直指定でも `espota` のUDP招待（ポート3232）に**無応答**（`No response from the ESP`）

ICMPは通るのにUDP往復が通らないのは、SSID名の `_g`（ゲスト回線らしき命名）が
示すとおり**VLAN間のクライアント分離**が疑わしい（デバイスの発信＝AWSへの
HTTPS送信は素通り、他ホストからの着信だけ塞がれる構成）。デバイス側のOTAサーバ
自体は起動ログで稼働を確認済みなので、ファーム実装の問題ではなくネットワーク
構成上の制約だった。試すには`unnamed_network_g`に実際に接続した端末（スマホ・
同SSID上のPC）から`espota`を叩くか、ルータ/APの当該SSID設定でクライアント
分離を確認する必要があったが、pull型が実機で確実に動くと確認できた
（§2冒頭）ため、この制約を回避してまでpush型を通す動機が無いまま放置されていた。

2026-08-10、「実際に届かず使っていない機能はDRAM/Flashの無駄では」という調査で
撤去した。`ArduinoOTA`本体・専用コールバック・`platformio.ini`の`-ota` env・
`DeviceIdentity`の`otaPassword`(NVS)・`tools/provision_device.py`の
`ota-password`コマンドを一式削除。静的RAMで約3.9KB、Flashで約39KB空いた
（`pauseSamplingForOta()`/`resumeSamplingAfterOtaFailure()`はpull型と共有の
安全停止シーケンスなのでそのまま残した）。詳細は
[log/2026-08-10-drop-lan-push-ota.md](log/2026-08-10-drop-lan-push-ota.md)。

もし将来LAN内pushを復活させる必要が出たら、まずこのVLAN分離を解消（対象SSIDの
クライアント分離設定を外す、または母艦を同じVLANに置く）してから、
このセクションと過去の実装コミット（`docs/log/2026-08-06-ota-arduino-ota.md`他）
を参照して作り直すことになる。

## 4. 未決事項・既知の割り切り

- **ロールバック未実装**（§2.9）。実機確認のタイミングでやる。
- **段階的ロールアウト**（1台だけ先に上げて様子見）は`pending_ota_version`を
  デバイス単位で持つ設計なので自然に表現できる（`request_ota.py`はdevice_id
  必須）。運用手順としては既に可能。
- device1・device2とも実チップは16MB（`partitions_16mb.csv`、`[env:esp32dev]`base側で
  指定）。パーティションサイズ差はビルドenv差に吸収される。NVSプロビジョニングも
  対象機と同じbase env(`provision`/`adxl355-provision`)からextendsしてパーティション表を
  揃えている（provision専用ビルドで誤って4MB既定に巻き戻すとspill容量が壊れるため）。
- ~~`pending_ota_version`を「消費しない」方針の副作用: 一致を確認した後もサーバ側
  の値が残り続けるため、後からUSBで別バージョンへ焼き直すと、デバイスが「要求と
  食い違う」と判断して勝手に元のバージョンへ戻す~~
  → **解消した**（2026-08-06、[docs/log/2026-08-06-ota-stuck-false-positive.md](log/2026-08-06-ota-stuck-false-positive.md)）。
  [2026-08-06-device1-16mb-confirm.md](log/2026-08-06-device1-16mb-confirm.md)で
  実際に踏んだのに続けて、同じ未クリア状態がwatchdogの停滞検知の誤検知
  （達成済みなのに「停滞」通知が出る）としても顕在化した。ingestが受信した
  バッチの`fw_version`が`pending_ota_version`と一致した時点で
  （`lambda/common/ota_watch.py`の`reached_target()`/`clear_ota_target()`）
  サーバ側が自動でクリアするようにした。「取得できるまでリトライ」は維持しつつ
  「達成後は解放する」形になった。
- ~~watchdogの停滞検知はサーバがデバイスの現在バージョンを知らず切り分けできない~~
  → **解消した**（2026-08-06、[docs/log/2026-08-06-device-status-fw-version-header.md](log/2026-08-06-device-status-fw-version-header.md)）。
  firmwareが毎バッチ`X-Namz-Fw-Version`ヘッダで現在版数を送るようになり、
  `namazu-devices`テーブルの`fw_version`属性・api `/devices`・ダッシュボードの
  デバイス一覧（版数列、OTA列は目標版数との一致判定）から外部で確認できる。
  ただし証明書検証失敗のような**原因そのもの**（版数が古いまま/理由不明で
  一致しない）の切り分けまではまだ自動化していない——実機のシリアルログを
  見に行く判断材料が増えた、という段階。
- **WiFi認証情報(SSID/パスワード)のOTA経由更新は未着手**。今はNVSに焼くのみで
  変更にはUSB書き直しが要る。暗号化した候補値をfirmware.binに埋め込んで配る
  作戦を検討済み（設計のみ、実装なし）:
  [docs/log/2026-08-11-wifi-credential-ota-rotation-plan.md](log/2026-08-11-wifi-credential-ota-rotation-plan.md)。
