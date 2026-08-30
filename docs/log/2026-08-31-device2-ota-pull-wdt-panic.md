# device2、OTA配信直前にTASK_WDTで再起動——原因はOTA取得経路自体のブロッキング読み取り

device2へ新版OTAを配信しようとした直前、`coredump/0002/a96e956-00001788108264719166.bin`
が自動アップロードされているのに気づいた。[2026-08-30の初回capture](2026-08-30-coredump-device2-first-real-capture.md)
とはファイル名の末尾（アップロード時刻）が異なる**別のcoredump**（約25時間後）で、実際に
シンボライズしたところ、既知の「batch送信のTLSハンドシェイク待ち」（PR#163〜170で対処済み）
とは**別経路の新しい原因**と判明した。

## 手順

[firmware/README.md](../../firmware/README.md#クラッシュ後のcoredump吸い出し)の手順を
USBシリアル経由ではなくS3から取得したファイル向けに適用した:

1. `aws s3 cp s3://namazu-data-486414336274/coredump/0002/a96e956-...719166.bin` で取得
2. S3キーの`fw_version`(`a96e956`)と同じコミットを`git worktree add --detach`し、
   `pio run -e adxl355`で`firmware.elf`を再現
3. `aws s3 cp s3://namazu-dashboard-486414336274/ota/adxl355/a96e956.bin`で実際に配信された
   バイナリを取得し、再ビルド版と`cmp -l`。差分は64バイトのみ（`esp_app_desc_t.app_elf_sha256`
   フィールド自体32バイト + 末尾チェックサム32バイト）——過去の照合と同型の差分パターンで、
   コード実体はビット一致と確認できた
4. `esp-coredump info_corefile --core <file> --core-format raw --gdb <toolchain-gdb> firmware.elf`。
   SHA256不一致チェック（`EspCoreDumpLoader.create_corefile`が投げる
   `ESPCoreDumpLoaderError`）は前回同様、実行時モンキーパッチで警告に格下げして読み進めた
   （corefile自体は例外より前に書き出し済みのため無視して問題ない）

## バックトレース

```
Crashed task: 'uploader'
task_wdt_isr → abort() → panic_abort
  → HTTPUpdate::runUpdate() → UpdateClass::writeStream()
  → Stream::readBytes() → WiFiClientSecure::read()/available()
  → data_to_read() → mbedtls_ssl_read() → mbedtls_ssl_fetch_input()
  → mbedtls_net_recv() → lwip_read()/lwip_recvfrom()  ← ここでブロック
```

`sampling`側の言及は無く(スタックはuploaderタスク単独)、**OTA本体(.bin)を取得中の
TLSソケット読み取りがブロックしたまま20秒のTASK_WDTに到達した**と確定した。
`checkAndPerformPullOta()` → `performPullOta()` → `httpUpdate.update()`の経路で、
`main.cpp`のコメント通り`onProgress`コールバックで`esp_task_wdt_reset()`を養う設計に
なっているが、**`onProgress`はチャンク書き込みが完了するたびに呼ばれるのであって、
1回のブロッキング読み取り呼び出しの最中には呼ばれない**——この1回が長引くと素通りする。

## 根本原因: OTA用ソケットにWDTより長いSO_RCVTIMEOがそのまま残っている

`performPullOta()`(`firmware/src/main.cpp:521`)が作る`WiFiClientSecure client`には
`setCACert()`しか呼んでおらず、**`setTimeout()`を一度も呼んでいない**。
`framework-arduinoespressif32`の`WiFiClientSecure`は`_timeout`の既定値が**30000ms**
（`WiFiClientSecure.cpp:35,56`）で、これが`connect()`時に`ssl_client->socket_timeout`
経由で`SO_RCVTIMEO`としてソケットへ`setsockopt`される（`ssl_client.cpp:88,138`）。
以後の`read()`/`available()`が内部で呼ぶ生のsocket `recv()`は、**この30秒が満了するまで
ブロックしうる**——WDTの20秒(`main.cpp:776`)より長い。ネットワークが一時的に詰まって
1回のTLSレコード読み取りが20秒を超えて止まると、`onProgress`の出番が来る前に
TASK_WDTが先に発火する。

`batch`送信側の`Uploader`は接続・ハンドシェイク・ヘッダ読み取りの各区間に明示的な
短いタイムアウトを持つ（[batch-uplink#27](https://github.com/nna774/batch-uplink/pull/27)、
v3.3.0で3000ms×3に短縮済み）が、**OTA取得経路はこの対策の外**——`Uploader`を経由せず
`HTTPUpdate`+生の`WiFiClientSecure`を直接使っているため、v3.3.0のタイムアウト短縮は
一切効かない。[docs/ota.md §2.5](../ota.md#25-安全な停止シーケンス)が「`onProgress`で
WDTを養う」と書いている設計は、複数チャンクにまたがる長時間更新には有効だが、
**1チャンク分の読み取りが単体で20秒を超えるケースへの対策にはなっていなかった**、
というのが今回の発見。

## この場の顛末（実害は軽微）

crashからの再起動後、device2はまもなく同じOTA取得を再試行して成功し、現在は
`fw_version: 70ae824`・`reset_reason: SW`で正常稼働中（`GET /devices/0002`で確認）。
1分バックオフ後の自然な再試行が効いた形で、手動介入は不要だった。ただし**再発すれば
毎回この経路で再起動しうる**——ネットワーク瞬断が起きやすいタイミング（OTA配信直後は
特にトラフィックが増える）と重なりやすい点は留意。

## 未着手

修正方針は未決定。候補（`docs/log/2026-08-29-device2-wdt-panic-fix-direction.md`で
batch送信側について挙がった3案と同型）:

- `performPullOta()`の`client`に`setTimeout()`で短いソケットタイムアウトを明示する
  （WDTの20秒を下回る値に）
- OTA取得中も定期的にWDTを養う仕組みを別途持つ（`onProgress`はチャンク単位なので、
  チャンク内部の待ちをカバーできる粒度に変える必要がある）
- WDT自体をさらに伸ばす（対症療法、他の本当のハングを検知する猶予も同時に伸びてしまう）

いずれもユーザー確認の上で着手する。
