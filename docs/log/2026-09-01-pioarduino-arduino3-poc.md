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

## batch-uplink側にPRを出し、マージされた

[nna774/batch-uplink#28](https://github.com/nna774/batch-uplink/pull/28)として
`#include <WiFi.h>`を1行追加するPRを提出し、ユーザー判断でマージ済み（`master`
`6ec000c`）。

## arduino-esp32 2.x（本番と同じ公式platform）でのリグレッション確認

マージ直後、**2.x側で壊れていないことを検証していなかった**とユーザーに指摘され、
実際に確認した。その過程で1件ローカル環境の事故を起こし、直した記録を残す。

### 事故: pioarduinoのインストールが公式platformの既定解決先を上書きしていた

`[env:esp32dev]`（本番と同じ設定、`platform = espressif32`とバージョン無指定）で
`batch-uplink#6ec000c`を使ってビルドしたところ、ログの`PLATFORM: Espressif 32
(55.3.311)`——**公式7.0.1ではなくpioarduinoが動いていた**。

原因: pioarduinoの`platform.json`は`"name": "espressif32"`と公式と同じ名前を
名乗っている。このPoCの最初の手順でpioarduinoのzipを`platform = <URL>`で
明示的にインストールした際、PlatformIOのパッケージマネージャが
`~/.platformio/platforms/espressif32`（バージョン無指定時の既定解決先）を
pioarduino版で上書きしてしまい、**このマシン上では`platform = espressif32`と
書いてあるどのenvも（本番のesp32dev/adxl355含めて）静かに3.x系を掴む状態に
なっていた**。commitされたコードには何の影響も無いが、**このマシンで
`pio run`する限り実機書き込みが意図せず3.x系になる**という、実害のある
ローカル環境汚染だった。

復旧作業中に並行して`pio pkg uninstall`と`pio run`を同時に走らせてしまい、
一時`framework-arduinoespressif32`が3.3.11(pioarduino版)のまま公式7.0.1に
紐付くという更に壊れた中間状態も踏んだ（`TypeError: expected str, bytes or
os.PathLike object, not NoneType`でビルド失敗）。教訓: **同じグローバル
`~/.platformio`ストアを触るpioコマンドを並列実行しない。**

最終的に`~/.platformio/platforms/espressif32`と壊れた
`~/.platformio/packages/framework-arduinoespressif32`を削除し、
`pio pkg install -g --platform "platformio/espressif32@7.0.1"`を単独実行で
やり直して復旧した。`framework-arduinoespressif32@3.20017.241212`
（=arduino-esp32 2.0.17相当）に戻っていることを確認済み。

### 本題: 2.x系でのビルド結果

`platform = espressif32@7.0.1`を明示指定した上で`batch-uplink#6ec000c`
（マージ済みfix込み）を使い`pio run -e esp32dev`——**SUCCESS**
（Flash 50.2%・RAM 19.3%）。`#include <WiFi.h>`の追加はarduino-esp32 2.x系にも
実害が無いことを実際に確認できた。検証後`platformio.ini`は`git checkout`で
元のコミット内容（タグpinのまま）へ戻し、コミットには一切影響していない。

### 今後への警告: pioarduinoと公式platformの名前衝突

**pioarduinoは`platform.json`の`name`を公式と同じ`espressif32`のまま配っている**
ため、同一マシンに両方を（`platform = <URL>`のようなバージョン無指定に近い形で）
入れると、今回のように既定解決先が上書きされうる。`[env:pioarduino-fake-sensor]`
を今後また実行する時は、この事故が再発しないよう次のどちらかを徹底すること:

- 本番系の全env（`esp32dev`・`adxl355`とその派生）の`platform`行を
  `espressif32@7.0.1`のように**バージョン明示pin**に変える（batch-uplinkの
  タグpinと同じ考え方。これをやっておけば、他のenvが何をインストールしようと
  本番envは既定解決先の汚染から免疫を持てる）。
- または`pioarduino-fake-sensor`のビルドだけ`PLATFORMIO_CORE_DIR`で
  別のホームディレクトリに隔離する。

このPoCの範囲では前者（本番envのバージョンpin化）を実施していない
（`platformio.ini`本体への変更提案はユーザー確認してから）。

## 現時点の評価・次にできること

- 3.x移行そのものは、ここまで見た限り**大掛かりな書き直しにはならなそう**——自前コードは
  ほぼ無改造、必要な修正はbatch-uplink側の1行のみ（今のところ判明している範囲では）。
  ただしこれはコンパイルが通っただけの確認であり、実機での動作（TFT_eSPI描画・OTA・
  coredump・WDT・パーティション境界など）は未検証。
- 進めるなら次はどちらか:
  1. [batch-uplink#28](https://github.com/nna774/batch-uplink/pull/28)をレビュー・マージし、
     新タグ（例: v3.3.1）を切る（Electabuzzにも影響する変更なので要相談・提出済み）。
  2. それを`pioarduino-fake-sensor`env（本番envとは別のまま）に取り込み、予備基板へ
     実際に焼いて長期間動かし、TFT_eSPI・OTA・coredump自動送信・WDT・DNS解決まわりが
     実機で問題なく動くか確認する。
  3. 十分な期間問題が出なければ、本番2台への展開を検討する（platform行の切り替えのみで
     済むはずだが、切り替え時は両機とも予備機同様の長期観察を経てから）。
- 「今すぐ3.xへ全面移行」ではなく、段階的に確認しながら進める前提——現状の2.x起因の
  クラッシュは自動再起動で自己回復しており、緊急性は無い
  （[2026-08-31-device1-lwip-null-deref-coredump.md](2026-08-31-device1-lwip-null-deref-coredump.md)）。
