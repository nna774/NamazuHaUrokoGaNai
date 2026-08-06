# OTA更新

ファームの無線更新。2026-08-06 に §2-A（ArduinoOTA、LAN内push）を実装した。
**実機での動作確認はまだ**（firmwareビルド[esp32dev/adxl355/両-ota env]・
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

将来 HTTPSプル型（`esp_https_ota`）が要る場面（外出先からの更新・無人運用）が
来たら別途検討する。現状2台とも自宅LAN内にあるのでpush型で足りている。

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
（`tools/provision_device.py add` が自動生成、`secrets-h` で `kOtaPassword` として
`firmware/src/secrets.h` に出る）。

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
  平文で書かない（secrets.h と同じ扱い）。`upload_port` はデバイスごとに違うので
  `--upload-port` で毎回指定する（platformio.ini には書いていない）。

## 6. 未着手

- 実機での動作確認（次回訪問時）。
- HTTPSプル型（外出先からの更新・無人運用が必要になった時点で検討。作戦は§7）。

## 7. 将来: HTTPSプル型（作戦、実装は未着手）

2026-08-06、作戦のみ検討した。前提: LAN内push（§2）は運用者が対象デバイスと同じ
LANにいる必要がある。外出先からの更新・無人運用にはデバイス自身がHTTPSで取得
（pull）する方式が要る。

### トリガー: リモート再起動と同型だが、値は「消費しない」

[リモート再起動](remote_restart.md)（手元から明示要求→バッチ送信レスポンスへの
便乗で気づく）と同じ設計を踏襲する。**デバイスが定期的に外部を自律ポーリングして
黙って最新へ追従する方式は採らない**——配布物（S3/CloudFront上のbin）の書き込み
権限が万一侵害された場合、無人運用中の全機へ運用者の操作なしにコードが流し込める
経路になり、pushより一段階ブラスト半径が大きい。「運用者が明示的に許可した時だけ
取得する」段を挟み、push型と同じ「意図した時にだけ書き換わる」信頼モデルを保つ。

- 手元: `tools/request_ota.py request <device_id> <version>` で `namazu-devices` に
  `pending_ota_version`（文字列）をセット。`cancel`/`list`も`request_restart.py`と同型。
- ingest `_handle_batch` が `pending_ota_version` を見て、あればレスポンスヘッダ
  `X-Namz-Ota-Version: <version>` を返す。
- **再起動要求と違い、返した直後にクリアしない。** 再起動要求は「一度実行したら
  意味を失うイベント」だが、OTAターゲットは「あるべき状態」なので照合し続けてよい。
  デバイスは埋め込みビルドバージョン（後述）と一致するまで、バッチ送信のたびに
  同じ指示を受け取り続ける。これは同時に**自然なリトライ機構**になる——ダウンロード
  失敗や書き込み失敗で古いバージョンのまま再起動しても、次のバッチ送信で再び気づいて
  再試行する。
- `Uploader::watchResponseHeader` は現状**単一ヘッダしか監視できない**
  （remote_restart.md）。再起動要求(`X-Namz-Restart`)と共存させるには、batch-uplinkの
  `Uploader`を複数ヘッダ監視に拡張する必要がある。

### 配布物: 既存CloudFrontに相乗り

新規ドメイン/ACM証明書を作らず、ダッシュボード配信で使っている既存の
CloudFront + S3に `ota/` プレフィックスで相乗りする。

```
ota/<env>/<version>.bin       # 例: ota/esp32dev-ota/<gitshorthash>.bin
ota/<env>/<version>.sha256    # 整合性チェック用
```

`env`はビルドターゲット（`esp32dev-ota`/`adxl355-ota`、将来16MB版等）。デバイスは
自分のenv名をビルド時定数として埋め込み済み（後述）にするので、サーバ側に
device_id→envの対応表を新設する必要はない（**変動軸を混ぜない**という
`tools/devices.json`の設計方針([design.md](design.md)「多点運用時のデバイス払い出し」)
をここでも踏襲。envはfirmware自身が知っていれば足りる）。

公開読み取り自体はapi/dashboardと同じ「認証なし公開」の割り切りに乗る
（バイナリ自体は秘密ではない）。書き込み（`aws s3 cp`）側の権限がそのまま信頼の
根っこになる点は、terraform stateやHMAC鍵と同じ扱い。

### バージョン識別: ビルド時にgit短縮hashを埋め込む

現状ファームにバージョン埋め込みが無い。`platformio.ini`にextra_script（Python）を
足し、`git rev-parse --short HEAD`を`-DNAMZ_FW_VERSION="..."`として注入する。作業
ツリーが汚れていたら`-dirty`サフィックスを付け、「未コミット状態を配布版として
掴む」事故を防ぐ。起動シリアルログにも出す（[memo.md](../memo.md)の残タスク
「起動時のログにバージョン/hash」がこれで一緒に片付く）。

### ダウンロード: esp_https_ota + push型と同じ安全停止シーケンス

- トリガーを検知したら、push型（§4）と同じ手順でRAMキューを退避する:
  測定タイマー停止→測定タスクをWDT監視から外す→`flushToSpill()`。
- `esp_https_ota`（ESP-IDF、Arduino coreから呼べる）で
  `https://<CloudFrontドメイン>/ota/<env>/<version>.bin`を取得。ブロッキングAPIの
  ままだと進行中にWDTリセットを挟めないので、低レベルAPI
  (`esp_https_ota_begin`/`perform`/`finish`)でループを回し、毎周
  `esp_task_wdt_reset()`を呼ぶ（ArduinoOTAの`onProgress`と同じ役割）。
- ダウンロード完了後、`.sha256`と突き合わせてから確定する。不一致なら
  `esp_https_ota_abort`し、測定を復旧して次バッチ送信でのリトライに任せる
  （上記のリトライ機構がそのまま効く）。
- 成功なら`ESP.restart()`。失敗系は測定タイマー・WDT登録を復旧して測定続行
  （push型`onError`と同じ）。

### ロールバック: pull型で初めて価値が出る

push型（§5）では「ロールバックは期待しない、最後の砦は物理アクセス」と割り切った。
pull型は**無人運用中の無人トリガー**なので、焼き損じた時に現地対応できない期間が
長くなりうる——ここで初めて自動ロールバックの価値が上回る。

`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`を有効化し、新イメージ起動後に「WiFi接続+
初回バッチ送信成功」を健全性の条件として`esp_ota_mark_app_valid_cancel_rollback()`
を呼ぶ。タイムアウト内に呼ばれなければブートローダが前スロットへ自動的に戻る。
**この変更はパーティションではなくbootloader設定なので、push型にも同時に効く**
（むしろ両方に恩恵がある）。実装するときは push型の§5「ロールバックは期待しない」
の記述もここで更新する。

### 未決事項（実装前に決めること）

1. **サーバがデバイスの現在バージョンを知る手段が無い。** ingestの
   `pending_ota_version`と実際に動いているバージョンの一致判定ができないと、
   「もう最新なのに毎バッチヘッダを返し続ける」（実害はないが無駄）状態になる。
   再起動要求のACK設計を参考に、焼き終わって再起動後の最初のバッチ送信で
   `X-Namz-Fw-Version`のような自己申告ヘッダをデバイス側から載せ、ingestが
   `pending_ota_version`と比較して一致したらクリアする経路を足すのが筋が良さそう。
2. **複数ヘッダ監視への`Uploader`拡張**が要る（再起動要求と共存させる場合）。
3. **段階的ロールアウト**（1台だけ先に上げて様子見）は`pending_ota_version`を
   デバイス単位で持てば自然に表現できる（`request_ota.py`はdevice_id必須なので
   既にそうなっている）。
4. 16MB機（`partitions_adxl355_16mb.csv`）のパーティションサイズ差はビルドenv差に
   吸収されるので、pull型固有の対応は不要（push型と同じ扱い）。
