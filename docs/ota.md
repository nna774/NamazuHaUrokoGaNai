# OTA更新

ファームの無線更新。2026-08-06 に §2-A（ArduinoOTA、LAN内push）を実装した。
device 2へのUSB書き込み・起動・OTAリスナー起動（`[ota] ready as namazu-2.local`）
までは実機で確認できたが、**push本体（`espota`での転送）は自宅ネットワークの
構成により母艦から直接は届かなかった**（§5「ネットワーク分離」参照）。実装自体の
不具合ではなく、試す場所を選ぶ運用上の制約。
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

- **push OTA転送そのものの実機確認**（次回、`unnamed_network_g` に接続した端末から）。
- HTTPSプル型（外出先からの更新・無人運用が必要になった時点で検討。デバイス発信の
  経路なら今回のネットワーク分離の影響を受けないという利点もある）。
