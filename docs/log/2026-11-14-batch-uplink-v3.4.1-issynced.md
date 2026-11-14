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

## 未確認

- OTAはまだ。実機に入れたら、コールドブート後と`esp_restart()`後の両方で、
  SNTP初回受信の後にサンプルが流れ始めることを確かめる。
- RTC引き継ぎ時刻がずれる原因（内蔵RCの較正誤差説）は検証していない。
- Electabuzzはv3.1.0のままにしている。取り込めばNOMINALアンカーの誤固定が直る。
