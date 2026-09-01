# arduino-esp32 3.x移行の実現性PoC（pioarduino経由）

[PR #191](https://github.com/nna774/NamazuHaUrokoGaNai/pull/191)でdevice1のlwIP内NULL参照crash
（`tiT`タスク、`dns_send`→`udp_sendto`経路）の真因が特定できていた:
`WiFiGeneric::hostByName()`がlwIPの「TCPIPスレッド専用」契約を破ってスレッドセーフでない
`dns_gethostbyname()`を直接呼んでおり、これはarduino-esp32 3.x系(Network/WiFi層を分離した
NetworkManager化)でのみ修正済み。うちが使うrelease/v2.x系(ESP-IDF 4.4.7)はEOLでバックポートは無い。

## 「今の2.0.17は積極的に選んだわけではない」への確認

`firmware/platformio.ini`は`platform = espressif32`とバージョン無指定。手元の
`espressif32 @ 7.0.1`（`https://github.com/platformio/platform-espressif32.git`、公式repo）を
確認したところ、同梱の`framework-arduinoespressif32`は`3.20017`——PlatformIOの表記の癖で
頭に`3.`を付けているだけで実体はarduino-esp32 **2.0.17**。公式リリースは6.9〜6.13あたりまで
確認できたが、いずれも中身はArduino Core 2.0.17 / ESP-IDF 4.4.7のまま。Espressif側が公式
PlatformIO連携のメンテを止めて以来ここで足踏みしており、**「バージョン無指定で最新を選んでも
2.0.17にしかならない」状態**——agentが古いのを選んだわけではなく、公式チャンネルの天井だった。

3.x/ESP-IDF 5.x系を使うには非公式のコミュニティフォーク`pioarduino/platform-espressif32`に
乗り換える以外に道が無い（`espressif/arduino-esp32#10039`で経緯が説明されている）。

## PoCの範囲

予備機(`fake-sensor`用の実センサ無しテスト機)だけを対象にした**コンパイルPoC**。
本番2台(esp32dev/adxl355)へは一切波及させていない。`firmware/platformio.ini`に
`[env:pioarduino-fake-sensor]`を追加し、`platform`だけをpioarduinoの最新安定タグ
`55.03.311`(Arduino 3.3.11 / ESP-IDF 5.5.5)のリリースzipへ固定して`pio run`した。

## 結果: 自前コード・主要ライブラリは無改造で通った、batch-uplinkだけ1点非互換

- インストール自体は成功（258MBの`esp32-core-3.3.11-libs.tar.xz`ダウンロードが1回だけ
  `ChunkedEncodingError`で切れたが、単純リトライで解消——コードの非互換ではない）。
- 自前ライブラリ（Adxl355・CoredumpQueue・DeviceIdentity・Display・Iis3dhhc・NamzWire・
  Shindo・TlsAllocProbe）、TFT_eSPI@2.5.43、ArduinoJson@7.4.3は**無改造でコンパイルが通った**。
  `src/main.cpp`・`src/piezo_main.cpp`が使う`WiFi`/`WiFiClientSecure`/`HTTPClient`の高水準APIも
  そのまま通った（`WiFi.begin()`/`.status()`/`.localIP()`等、コード側は既にArduino core 3.x互換
  の書き方だった）。
- 唯一の非互換: `batch-uplink`(Electabuzzと共有する外部repo、v3.3.0)の`Uploader.cpp`が
  ```
  error: 'WiFi' was not declared in this scope
  ```
  で落ちる。原因は`Uploader.cpp`が`<WiFiClientSecure.h>`のみincludeし`<WiFi.h>`を明示
  includeしていないこと。2.x系では`WiFiClientSecure.h`が`WiFi.h`を暗黙に引き込んでいたが、
  3.x系はNetwork層とWiFi層を分離した(`WiFiClientSecure.h`は`NetworkClientSecure.h`への
  薄い後方互換ラッパーになった)ため、その暗黙includeが切れた——**PR#191で見つけた
  クラッシュの根治そのものである分離が、そのままここにも波及した形**。

## ローカル検証: 1行修正で解消することを確認

`batch-uplink`本体（Electabuzzと共有、このfirmwareリポジトリ単体では直せない）へは
触れず、ジョブの一時ディレクトリにv3.3.0のローカルcloneを作り、`Uploader.cpp`へ

```cpp
#include <WiFi.h>
#include <WiFiClientSecure.h>
```

の1行を足しただけの版を`pio run -e pioarduino-fake-sensor`のlib_depsに一時的に向けて
再ビルドしたところ、**フル成功**（リンク・パーティション生成・イメージ作成まで完走、
Flash 55.8%・RAM 19.9%）。2.x系にも実害の無い変更のはず（既に暗黙に使えていたヘッダを
明示するだけ）。

検証後、`platformio.ini`の`[env:pioarduino-fake-sensor]`は元のGitHubタグ pin
（`batch-uplink.git#v3.3.0`、未パッチ）に戻してある——**現状のままではこのenvはビルドが
通らない**。理由はコメントに残した。

## 現時点の評価・次にできること

- 3.x移行そのものは、ここまで見た限り**大掛かりな書き直しにはならなそう**——自前コードは
  ほぼ無改造、必要な修正はbatch-uplink側の1行のみ（今のところ判明している範囲では）。
  ただしこれはコンパイルが通っただけの確認であり、実機での動作（TFT_eSPI描画・OTA・
  coredump・WDT・パーティション境界など）は未検証。
- 進めるなら次はどちらか:
  1. batch-uplink側で`#include <WiFi.h>`を足したPR・新タグ（例: v3.3.1）を出す
     （Electabuzzにも影響する変更なので要相談）。
  2. それを`pioarduino-fake-sensor`env（本番envとは別のまま）に取り込み、予備基板へ
     実際に焼いて長期間動かし、TFT_eSPI・OTA・coredump自動送信・WDT・DNS解決まわりが
     実機で問題なく動くか確認する。
  3. 十分な期間問題が出なければ、本番2台への展開を検討する（platform行の切り替えのみで
     済むはずだが、切り替え時は両機とも予備機同様の長期観察を経てから）。
- 「今すぐ3.xへ全面移行」ではなく、段階的に確認しながら進める前提——現状の2.x起因の
  クラッシュは自動再起動で自己回復しており、緊急性は無い
  （[2026-08-31-device1-lwip-null-deref-coredump.md](2026-08-31-device1-lwip-null-deref-coredump.md)）。
