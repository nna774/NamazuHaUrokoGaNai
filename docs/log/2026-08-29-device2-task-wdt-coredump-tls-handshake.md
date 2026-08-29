# 2026-08-29 device2のTASK_WDT再起動をcoredumpで実証、SPI配線説を覆す

PR #163の事後解析中に気づいたdevice2の周期的約37秒欠落（原因は`TASK_WDT`と判明済みだったが、
根本原因は「ファーム側の対応は別セッションで継続中」のまま未着手だった）を、実際に調査した。

## 経過

- `GET /devices/0002`で確認したところ、その場でまさに`reset_reason: "TASK_WDT"`・
  `uptime_s: 276`と出ており、数分おきに再起動が続いている状態だった。
- ユーザー案「メモリ不足では」を検討したが、直後の`heap_free_bytes: 71808`はクラッシュ
  直前の値ではない（再起動直後のスナップショット）ため肯定も否定もできず保留。
- **SPI配線接触不良説（`docs/adxl355.md` §5.1.1の既知の持病）を検討したが、却下した。**
  ESP32はSPIマスターとして自らクロックを出すため、スレーブ(ADXL355)が応答しなくても
  `spi_.transfer()`は既定クロックで決まった時間内に必ず返る（I2Cのクロックストレッチの
  ような「相手待ちで止まる」機構がSPIには無い）。過去の「3軸すべて0」現象は**誤読**であり
  **ハング**ではなく、「WDTが20秒間一度も養われない」症状の説明にならない。
- ユーザーが`pio device monitor | tee`でシリアルを直結したところ、**100分以上再起動が
  発生しなくなった**。配線に触れたことが影響した状況証拠に見えたが、これだけでは
  「原因がSPI」と「原因はネットワークだが配線を触った拍子にアンテナ周りの取り回しが
  変わった」を区別できず、決定打にはならなかった。

## coredump-to-flashの発見と読み出し手順の確立

シリアルを常時つながなくても事後に原因を特定する方法を探したところ、**ファームを一切
変更しなくても既に使える状態になっていた**と分かった（吸い出し方の実用的な手順は
[firmware/README.md](../../firmware/README.md#クラッシュ後のcoredump吸い出し)に
まとめた）:

- `firmware/partitions_16mb.csv`に`coredump`パーティション(64KB, offset 0xFF0000)が
  既に確保済み
- arduino-esp32の既定sdkconfigで`CONFIG_ESP_COREDUMP_ENABLE_TO_FLASH=y`（ELF形式）が
  **最初から有効**
- WDTは`trigger_panic=true`で設定済みなので、パニック時にESP-IDFの標準機能として
  タスクごとのレジスタ/バックトレースが自動でこのパーティションに書き込まれる。
  次に別の原因でもう一度落ちるまで上書きされず残るため、**発生の瞬間に立ち会う必要が
  ない**。

この機能自体は今回初めて存在に気づいた（過去のdevice1調査（2026-08-08〜09、下記参照）は
すべてシリアル直結でのリアルタイム観察に頼っていた）。読み出し手順は以下の通り確立した:

1. `pip install esp-coredump`（`.venv`へ。PEP668によりシステムPythonへは直接入らない）
2. 実機の`fw_version`（gitの短縮hash、`976bd93`）と同じコミットをdetached worktreeで
   チェックアウトし、同じenv(`adxl355`)で`pio run`して`firmware.elf`を再現
3. `esp-coredump`はESP-IDFの`parttool.py`（パーティション情報を実機に問い合わせる補助
   スクリプト）に依存するが、フルのESP-IDFは未インストール。パーティション表は
   `partitions_16mb.csv`から値が分かっているので、`$IDF_PATH/components/partition_table/
   parttool.py`に「既知の値を無条件に返すだけ」のスタブを自作して代替した
4. `esp-coredump info_corefile --off 0xFF0000 --gdb <toolchain-xtensa-esp32-elf-gdb> firmware.elf`
   で実機からcoredumpを直接読み出せた。GDBは`~/.platformio/packages/toolchain-xtensa-esp32/
   bin/xtensa-esp32-elf-gdb`を流用（PlatformIO Arduinoフレームワークには同梱されていないが
   toolchainパッケージには入っている）
5. **SHA256不一致で一度弾かれた**（`coredump SHA256(...) != app SHA256(...)`）。ソースは
   同一コミットだが、`esp_app_desc_t`に焼き込まれるビルド日時(`__DATE__`/`__TIME__`)が
   再ビルド時に変わるため、コード自体が同一でも画像のSHA256は一致しない。この
   チェックはコード配置のズレ（＝バックトレースの誤解決）を防ぐためのものだが、
   ズレの原因がビルド日時のみと判断できたため、`esp_coredump`のsite-packagesは編集せず
   実行時モンキーパッチでこのチェックを警告に格下げして読み進めた

## 結果: SPI配線説は完全に否定、2026-08-08のdevice1仮説がdevice2で再発と確定

読み出せたcoredumpのバックトレース:

```
uploaderTask() main.cpp:642
→ Uploader::pump() → Uploader::postBatch() Uploader.cpp:392
→ HTTPClient::POST()/sendRequest()/connect()
→ WiFiClientSecure::connect()
→ start_ssl_client() ssl_client.cpp:277 (vTaskDelay(2)のハンドシェイク待ちループ)
```

`sampling`タスクは`ulTaskGenericNotifyTake`で次のタイマー通知を待つ健全な状態のまま
だった。**SPI/センサ側の異常は無く、`uploaderTask`がTLSハンドシェイク待ちで20秒間WDTを
養えずパニックしていた**と確定した。

これは`docs/design.md`「送信の信頼性」に2026-08-08〜09で記録したdevice1の仮説
（`uploaderTask`のtask watchdogがTLSハンドシェイクの内部待ちより先に発火する）と
**全く同じ機構がdevice2で再発している**ことを示す。ただし当時は実際のバックトレースを
一度も取れておらず、タイミングの一致や意図的な全断実験からの推測にとどまっていた
（同ドキュメント2026-08-09の記述参照）。**coredumpで実際のスタックを直接確認できたのは
今回が初めて。**

### 気になる点: 既存の緩和策だけでは防げていない

`batch-uplink`にはこの機構への対策として`client_.setHandshakeTimeout(4000)`
（[batch-uplink#11](https://github.com/nna774/batch-uplink/pull/11)、v2.2.0、2026-08-09実装済み）
と、WDT自体の10秒→20秒への拡張（`main.cpp`、同日）が既に入っている。にも関わらず
今回20秒近くまで詰まった。`ssl_client.cpp`を読むと、`setHandshakeTimeout()`が効くのは
`mbedtls_ssl_handshake()`の**呼び出し間**だけで、その中の個々のソケット`recv()`の
タイムアウト(`SO_RCVTIMEO`)は接続タイムアウト(`WiFiClientSecure::connect(..., timeout=5000)`)
から流用されており、ハンドシェイクタイムアウトとは別物。TCP接続確立(最大5秒)＋
ハンドシェイクループ中の重いrecv()一発(最大5秒)＋ハンドシェイク自体の判定(4秒)が
直列に積み上がると、**個々のタイムアウト値は妥当でも合計がWDTの20秒に迫りうる**、
という新しい疑いが残った。修正は未実装・方針未決定のまま。

## 次に何が可能になったか

- **coredump読み出し手順が確立した。** 以後の同種障害は、発生に立ち会えなくても
  事後にUSBを挿すだけで実際のバックトレースを取れる。これまでのdevice1調査
  （2026-08-08〜09）は全てリアルタイムのシリアル直結観察に頼っていたが、今後は不要になる。
- **将来構想（未実装・アイデア段階）**: 次に再起動を検知したら、起動直後に
  coredumpパーティションを読んでクラウド（S3等）へ自動アップロードする仕組みを
  作りたい。今回は手動でUSB接続して読み出したが、これが自動化できれば「気づいたら
  直っていた」ケースでも原因調査ができるようになる。実装方法は未検討（起動時に
  coredumpの有無を確認するAPIがESP-IDFにあるはず、送信先・認証・容量は要検討）。
- 修正方針（タイムアウトの合計を再設計する／`postBatch()`中もWDTを養う／WDTをさらに
  伸ばす、の3案）はユーザーとの相談待ちで未着手。
