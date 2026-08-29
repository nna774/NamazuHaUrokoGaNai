# coredump自動クラウド送信の実装プラン

[2026-08-29-coredump-auto-upload-design-discussion.md](2026-08-29-coredump-auto-upload-design-discussion.md)・
[2026-08-29-coredump-auto-upload-design-continued.md](2026-08-29-coredump-auto-upload-design-continued.md)
で詰めた設計をもとに、Explore調査(firmware側のHMAC署名・LittleFS初期化・POSTパターン、
lambda/terraform側のルーティング・S3キー命名・ライフサイクル・通知パターン)を経て
実装プランを作成し、承認を得た。実装はこのプランに沿って進める。

## Context

PR#165でdevice2のTASK_WDT再起動をESP-IDFのcoredump-to-flash機構（既定で有効）で
読み出せることが分かったが、これは手動でUSBを挿して初めてできる調査であり、かつ
coredumpパーティション（64KB、`firmware/partitions_16mb.csv`の`coredump,0xFF0000,0x10000`）は
**単一image・次のパニックで上書き**という制約がある(`espcoredump`ヘッダの
`esp_core_dump_image_get()`/`esp_core_dump_image_erase()`のAPI設計から確認済み)。device2のように
同じ機構が周期的に再発するケースでは、原因調査の前に証拠が消える。

主な設計判断とその理由:
- **秘密情報(WiFiパス・HMAC鍵)が写り込むかもしれない前提で扱う**。実機sdkconfigはDRAM全体
  captureが無効でタスクスタック/レジスタのみが既定の記録対象だが、絶対に写らない証明には
  ならないため、保存先を非公開に隔離する
- **単一スロット問題への対処として、起動直後・WiFi接続前にLittleFSへコピーしてから、
  ハードウェア側のパーティションを空ける**。クラッシュループでLittleFS側が溢れないよう
  リングバッファ(上限件数・drop-oldest)にする
- **アップロードは新しい常駐taskを作らず、`setup()`内、`gUploader`生成前の同期呼び出しにする**。
  `main.cpp`が`setup()`冒頭で`tlsmempool::install()`しているmbedTLS用固定プールは
  「単一TLS接続前提」(OTAが`closeConnection()`してからCloudFrontへ張り直すのと同じ制約)なので、
  この順序ならcoredump送信用TLS接続だけが存在する状態を保てる
- `Uploader`(batch-uplink)は経由させない。batch-uplinkは測定対象非依存という設計原則があり、
  coredumpの送信先・形式はnamazu固有のため
- 対象は`main.cpp`を共有する device1(esp32dev)・device2(adxl355、`[env:adxl355]`が
  `extends = env:esp32dev`)のみ。device3(piezo、`piezo_main.cpp`が別)は今回のスコープ外とする

## 実装

### 1. firmware: coredump→LittleFSコピー（起動直後・WiFi接続前）

新規ファイル `firmware/lib/CoredumpQueue/`（`Uploader`と同様、独立したlib）に以下を実装:

- `hasHardwareCoredump()`: `esp_core_dump_image_get(&addr, &size)`が`ESP_OK`かどうかで判定
- `copyHardwareCoredumpToQueue(const char* dir)`: 見つかった場合、
  `esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_COREDUMP, nullptr)` +
  `esp_partition_read()`で生バイト列を読み出し、NVS(`Preferences`)の連番カウンタ
  （`DeviceIdentity.cpp`と同じ`Preferences`パターンを流用、新しいnamespace/keyを1つ追加）を
  インクリメントしながら`<dir>/<seq:010d>.bin`へ書く。書き込み成功を確認できたら
  `esp_core_dump_image_erase()`でハードウェア側を空ける。この一連はネットワーク非依存の
  ローカルflash操作のみ
- `enforceQueueLimit(const char* dir, size_t maxFiles)`: ディレクトリを列挙してファイル数が
  上限を超えていたら、ファイル名（連番なので辞書順=時系列）でソートし古い方から削除。上限は
  `config.h`に`kMaxCoredumpFiles`として定義（既定8件を提案、63KB×8≈500KB、spillパーティション
  11.87MBに対して無視できる量）
- `LittleFS.open()`/`openNextFile()`使用時は`Uploader.cpp`の`loadOldestSpillPath()`にある
  「ヒープ逼迫時に未捕捉例外→abortしうる」注意点を踏襲し、try/catchで握りつぶす

`main.cpp`の`setup()`冒頭、`tlsmempool::install()`の直後・identity未プロビジョニングチェックより
前に呼ぶ（WiFi/identityに依存しないため最速で実行できる）。`LittleFS.begin(true)`をここで自前で
呼ぶ必要がある（現状`Uploader::begin()`が唯一のマウント元）。`Uploader::begin()`が後で再度
`LittleFS.begin(true)`を呼んでも問題ないはずだが、実機で二重mountが安全か確認する（下記
verification参照）。

### 2. firmware: LittleFS→クラウドアップロード（WiFi接続後）

新規関数 `drainCoredumpQueue()`（`CoredumpQueue`libまたは`main.cpp`内static関数）を、
`setup()`内`connectWifi()`成功確認後・`gUploader = new Uploader(...)`より前に呼ぶ。

- `/coredump/`内のファイルを連番順に1件ずつ処理
- 署名: `batch-uplink`の`src/HmacSha256.h`が公開している
  `hmacSha256Hex(const char* key, const uint8_t* data, size_t len)`をそのまま使う（`Uploader`外から
  呼べることを調査で確認済み）。ファイル全体をメモリに載せず署名するのは難しいため、64KB以下
  という上限を踏まえ署名計算用にはバッファへ読み込んでよい（HTTPボディのストリーミングとは
  別の話）
- POST: `WiFiClientSecure` + `HTTPClient`を素朴に使う。TLSルート証明書は`performPullOta()`と同じ
  `amazon_root_ca1_pem_start`+`setCACert()`パターン。ボディは
  `HTTPClient::sendRequest("POST", &file, fileSize)`でLittleFSの`File`を`Stream*`として直接渡し、
  64KB全体のmallocを避ける
- ヘッダ: `X-Namz-Device`(device_id)・`X-Namz-Signature`(署名)・`X-Namz-Fw-Version`(`kFwVersion`、
  既存バッチが送っているのと同じヘッダ名)
- タイムアウト: `setHandshakeTimeout(4000)`＋`millis()`ベースの自前デッドライン（1件あたり・全体
  それぞれ）。WDTには頼らない
- 200系が返ったファイルだけ削除。それ以外（タイムアウト・非2xx・WiFi未接続）は残して次回起動時
  に再試行

送信先URLは新規プロビジョニング項目を増やさず、`gIdentity.ingestUrl + "/coredump"`を組み立てる
（`DeviceIdentity`に新フィールド不要と確認済み）。

### 3. lambda: `/coredump`ルート追加

`lambda/ingest/handler.py`:
- `handler()`のルーティングに`path.rstrip("/").endswith("coredump")`の分岐を追加、
  `auth.verify(device, raw, sig)`は既存の共通処理をそのまま通す（`auth.verify`は生バイト列に
  対する検証でバッチのwire formatに依存しないことを確認済み）
- 新規`_handle_coredump(raw, device, headers)`: `s3util.coredump_key(...)`でキーを組み立てS3へ
  `put_object`。成功したら`notify.from_env().notify(...)`でSlack通知（失敗してもACKには
  影響させない——`devices.get_device`失敗時と同じ「主経路ではないので握りつぶす」扱い）。
  通知メンションはwatchdogの`SLACK_MENTION = "<@U0323ESK6> "`と同じ値をingest側にも定義して使う
- 200を返すのはS3書き込み成功時のみ

`lambda/common/s3util.py`:
- `COREDUMP_PREFIX = "coredump"`
- `coredump_key(device_id: int, fw_version: str, uploaded_at_us: int) -> str` →
  `f"{COREDUMP_PREFIX}/{device_id:04d}/{fw_version}-{uploaded_at_us:020d}.bin"`（`raw_key`と同じ
  ゼロパディング規則。fw_versionをキーに含めるのは、既存のcoredump読み出し手順が
  「fw_versionと同じコミットでelf再ビルド」を前提にしているため、S3の場所から直接わかるように
  する）

IAM変更は不要（`terraform/iam.tf`の`S3Data`ステートメントが`aws_s3_bucket.data.arn`＋ワイルドカードで
既にPutObjectまで許可済み、ingest/watchdog等全Lambdaで共有する単一ロール）。

### 4. terraform: `coredump/`のライフサイクル

`terraform/s3.tf`の`aws_s3_bucket_lifecycle_configuration.data`に新しい`rule`ブロックを追加:
```hcl
rule {
  id     = "expire-coredump"
  status = "Enabled"
  filter {
    prefix = "coredump/"
  }
  expiration {
    days = 60
  }
  noncurrent_version_expiration {
    noncurrent_days = 30
  }
}
```
`expire-raw`ルールと同じ構造、日数は変数化せず直値。`data_bucket_protect_events`のDenyは
`events/*`のみが対象で`coredump/`とは重ならないため抵触しない。

## 実装順序（コミット分割の目安）

1. lambda + terraform（`/coredump`ルート・S3キー・lifecycle） — 単体でテスト可能、firmwareより
   先に着手できる
2. firmware: coredump→LittleFSコピー＋ハードウェア側erase（ネットワーク非依存の部分から）
3. firmware: LittleFS→クラウドアップロード（署名・HTTP・リングバッファ運用）

## 検証

- **lambda**: `pytest lambda/tests`。既存スタイル（`test_devices_update_integration.py`のように
  `handler()`を直接呼ばず、`_handle_coredump`やハンドラ内のロジック単位を切り出してテスト）に
  倣い、`s3util.coredump_key()`の単体テストと、`_handle_coredump`をS3クライアントのモック
  （`FakeTable`相当）でテストする。既存の159件超のテストが通ることも確認
- **firmware**: `pio run -e esp32dev -e adxl355`でコンパイルが通ることを確認。実際の動作確認は
  現物の再起動なしには困難なため、デバッグ用に意図的なpanic（`abort()`等）を一時的なトリガー
  経由で起こせるようにし、実機（できれば予備基板）で: (a) coredumpパーティションがLittleFSへ
  コピーされ`esp_core_dump_image_erase()`後に空になること、(b) 次回WiFi接続後にS3へ
  アップロードされること、(c) Slack通知が飛ぶこと、(d) アップロード成功後にLittleFSのファイルが
  消えること、を確認する
- **LittleFS二重mount**: `LittleFS.begin(true)`をcoredumpコピー時と`Uploader::begin()`時の2箇所で
  呼ぶことになるので、実機ログで2回目の`begin()`がエラーにならないか確認する
- 一連の変更後、`docs/design.md`の構想メモを「実装済み」に更新し、実装ログを`docs/log/`に追記する
