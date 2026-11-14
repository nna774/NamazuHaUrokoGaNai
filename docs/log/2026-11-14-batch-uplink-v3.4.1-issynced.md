# batch-uplink v3.4.1: isSynced()がソフトリセット直後の時刻を同期済みと誤認しないようにする

2026-11-14、device2がTLSハンドシェイク待ちでTASK_WDTを2回続けて起こした。2回目の
起動では、RTCから引き継いだ約+3130秒先の時刻がSNTP応答の前から同期済みとして
扱われた。その結果、未来時刻のrawバッチが1本でき、coredumpのクラッシュ推定時刻も
誤った値になった（事件の詳細は同日の device2-back-to-back-tls-wdt-and-clock-jump ログ）。

## 決めたこと

- **batch-uplinkの`timesync::isSynced()`を「この起動でSNTPの応答を一度でも受け取ったか」
  に変えた**（[nna774/batch-uplink#30](https://github.com/nna774/batch-uplink/pull/30)、v3.4.1）。
  判定は`onSync`コールバックの末尾で立てるatomicフラグで行う。旧判定の後半にあった
  年判定(`time > 2023-11`)は、ソフトリセットでRTCから引き継いだ時刻を素通しにしていた。
- `sntp_get_sync_status()`に一本化しなかった理由はESP-IDFのsntp.cで確かめた。
  COMPLETEDは一度読むとRESETに戻り、SMOOTHではslew中IN_PROGRESSのままになる。
  そのため「一度でも同期したか」の判定には使えない。年判定はこれを補うものだったと見ている。
- pinは`firmware/platformio.ini`と`terraform/build_lambda.sh`の両方をv3.4.1に揃えた。
  Lambda側は**v3.3.0のまま取り残されていた**（09-01にファームだけv3.4.0へ上げた時に
  揃え漏れていた）。v3.3.0〜v3.4.1でPython側(`batch_uplink/`)に差分は無いので、
  Lambdaの中身は変わらず、揃え直しても挙動は変わらない。

## 許容した副作用

ソフトリセット後は、SNTPの初回受信までサンプルを捨てる（`main.cpp`の
`if (!timesync::isSynced()) continue;`）。コールドブートでは元々そうしていた。通常は
WiFi接続とSNTPの初回問い合わせを待つ数秒で終わる。WiFiが落ちたままならその間ずっと
捨てるが、そこで残せるのはRTC由来の未検証の時刻付きのバッチだけで、震度計算にも
事後解析にも使えない。だから捨てる方を選んだ。

`gRtcLastAlive`と`RtcPumpTrace.startedUs`は、同期前は「誤った時刻」ではなく
「不明(0)」になる。今回の誤ったクラッシュ推定時刻はこれで防げる。

## 2号機へのOTA（同日）

master `a6c495d`（#269のマージコミット）をadxl355向けに公開し、device 2へ当てた。
許可を出してから約1分で`fw_version: a6c495d`、`reset_reason: SW`で立ち上がった。
OTA後の再起動はソフトリセットなので、今回直した経路そのものを通っている。

- 再起動後の最初のバッチは、起動(`boot_epoch_us`)から19.8秒後に始まった。
  以後は15.1秒ごとに隙間なく届いている。
- 新しいバッチの開始時刻はすべて受信時刻より前で、未来時刻のバッチは出ていない。
- 再起動の前後で欠けたのは約26秒ぶん（再起動直前の最後のバッチの終わりから、
  同期後の最初のサンプルまで）。

### OTAの取得中にTASK_WDTが2回起きた

着地する前に、旧ファーム(cf36e46)がOTA取得中のTASK_WDTで2回落ちていた。
3回目の試行で着地した。自動回収されたcoredumpは
`coredump/0002/cf36e46-00001794654988968166.bin`(推定20:15:55)と`...655041968045.bin`
(推定20:16:44)。S3の`ota/adxl355/cf36e46.elf`で解決すると、2本とも
`uploader`タスクが`performPullOta`(main.cpp:591)→`HTTPUpdate::runUpdate`
(size=1059728 = a6c495d.bin)→`UpdateClass::writeStream`→`Stream::readBytes`→
`WiFiClientSecure::read`→`mbedtls_ssl_read`→`lwip_recvfrom`でブロックしたまま
`task_wdt_isr`→`abort()`に至っていた（`exccause=StoreProhibited`は残り値で、
今回の原因とは関係ない）。[2026-08-31](2026-08-31-device2-ota-pull-wdt-panic.md)と同じ型である。
本体を取得している途中のTLS読み取り1回が20秒を超えていて、`onProgress`のWDT給餌は
チャンクごとにしか呼ばれないので、すり抜けている。

時系列: 20:15:36 公開 → 許可 → A(cf36e46)が20:15:55ごろ取得を開始して落ちる →
B(20:16:28起動)も20:16:44ごろ取得を開始して落ちる → C(20:17:21起動)が取得に成功し、
20:17:43にa6c495dで起動。許可はサーバ側に立てたままなので、パニック後も自然に再試行される。
OTAが終わるまでの欠測は、20:16:01〜20:17:22と再起動前後の約26秒。

[2026-09-06](2026-09-06-ota-pull-timeout-budget-fix.md)では、read/writeの締切は
HTTPUpdateが8秒に揃えているので危険域ではない、と判断した。だが`Stream::readBytes`は
1バイトごとに`timedRead`(各8秒)を呼ぶので、データが細切れに届くと1チャンクの読み取りは
8秒で打ち切られず、20秒を超えうる（推測。実機では確かめていない）。2号機では今日、
postBatchのTLS待ちWDTも出ており、回線が遅い時間帯だった可能性がある。

## 未確認

- コールドブート（電源投入）後の経路は、実機ではまだ確かめていない。
- 1号機(esp32dev)と3号機(piezo)にはまだ当てていない。
- OTA取得中のWDTの対策（`readBytes`の打ち切りの見直し、またはタスクWDTからの一時的な外し）は未着手。
- RTC引き継ぎ時刻がずれる原因（内蔵RCの較正誤差説）は検証していない。
- Electabuzzはv3.1.0のままにしている。取り込めばNOMINALアンカーの誤固定が直る。
