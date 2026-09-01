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

このPoCの範囲では前者（本番envのバージョンpin化）を実施していない。
**どうするか(pinするか/PLATFORMIO_CORE_DIRで隔離するか)はユーザーが検討中——
下のTODOに置く。**

## 現時点の評価

**「3.x移行はPR#191のlwIPクラッシュを直す・自前コードはほぼ無改造で済む」という
当初の見立ては、実機検証の結果どちらも支持されなくなった。** 詳細は下の
「実機で本題のバグを再現した」参照。3.x移行そのものの実現性（コンパイルは通る）は
維持できているが、移行の主目的（クラッシュの根治）が果たされるかは現時点では
**否定的な材料の方が多い**。「今すぐ3.xへ全面移行」を進める根拠は薄れた——
現状の2.x起因のクラッシュは自動再起動で自己回復しており、緊急性は無い
（[2026-08-31-device1-lwip-null-deref-coredump.md](2026-08-31-device1-lwip-null-deref-coredump.md)）ので、
急いで乗り換える理由も無い。

## batch-uplinkにタグを切り、予備基板へ実際に書き込んだ

[v3.3.1](https://github.com/nna774/batch-uplink/releases/tag/v3.3.1)を`6ec000c`に
切って公開（このリポジトリ初のパッチバージョンタグ）。PR#28の概要欄にも2.x側の
確認結果を追記した。`[env:pioarduino-fake-sensor]`のlib_depsをこのタグへ向けて
テスト機（`/dev/cu.usbserial-5B320272871`、CH9102系）へ書き込み——**ビルド・書き込み
自体はSUCCESS**。

### シリアルログで見えた挙動: 起動・バッチキューは正常、WiFi再接続に問題あり

起動直後はWiFi接続・TLS POST試行・RAMキュー→spill退避まで一連の動作をしており、
**クラッシュ・パニック・WDTリセットは一切無い**（PR#191のDNS/hostByName系クラッシュは
この観測時間内では未再現、当然だが再現には時間がかかる類のものなので「出なかった」
だけでは無罪証明にならない）。

一方で、しばらく観察していると以下が繰り返し出た:

```
[ WARN ][STA.cpp:145] _onStaArduinoEvent(): Reason: 204 - HANDSHAKE_TIMEOUT
[wifi] FAILED
[uplink-debug] pump: wifi not connected (status=5)
E wifi:sta is connecting, cannot set config
[ERROR][STA.cpp:417] connect(): STA clear config failed! 0x3006: ESP_ERR_WIFI_STATE
E esp_littlefs: Unable to allocate FD
[ERROR][vfs_api.cpp:312] VFSFileImpl(): fopen(/littlefs/spill/....bin, r) failed: 22 (Invalid argument)
```

`main.cpp`の`connectWifi()`（`WiFi.status() != WL_CONNECTED`を見て`WiFi.begin()`を
呼び直すだけの単純な再接続ループ、2.x時代からある実装）が、`STA.cpp`
（3.x系でのNetwork/WiFi分離後の新ファイル）側の「まだ接続処理中に`WiFi.begin()`を
呼ぶとconfigをclearできない」状態にハマって再接続が詰まっている様子。
LittleFSの`Unable to allocate FD`も同時に出ており、こちらはこの基板が過去の
別PoC（tls-alloc-probe等）で使い回されている影響の可能性もあり、3.x固有かは未切り分け。

**環境要因ではない**——ユーザーから、同じ場所・同じ基板構成で2.x系ファームは
問題なく動いていたと確認が取れたため、ベンチのAP電波状況が原因という線は消えた。

### 既知のarduino-esp32 3.x系バグと判明

Web検索したところ、まったく同じ症状（`wifi:sta is connecting, cannot set config`、
core 3.3系で発生、2.x/3.0時代には無かった）が
[HomeSpan#1148](https://github.com/HomeSpan/HomeSpan/discussions/1148)で報告されて
いた。原因はarduino-esp32 3.x系で**WiFiの自動再接続(auto-reconnect)がバックグラウンド
で有効になっている**こと——`connectWifi()`（`WiFi.status()`を見て自分で`WiFi.begin()`
を呼び直すだけの2.x時代からの実装）が、自動再接続が接続試行中のところへ重ねて
`WiFi.begin()`を呼んでしまい、`STA.cpp`側の状態管理と衝突して二度と繋がらなくなる。
回避策として`WiFi.setAutoReconnect(false)`を`begin()`前に呼ぶ、または再接続前に
明示`WiFi.disconnect()`を挟む、が報告されている。

**「3.x移行は自前コードほぼ無改造で済みそう」という当初の評価は訂正が要る**——
少なくとも`connectWifi()`（`main.cpp`・`piezo_main.cpp`双方にある同型の実装）は
3.x系向けに手を入れる必要がある。

LittleFSの`Unable to allocate FD`は、この基板が過去の別PoC（tls-alloc-probe等）で
使い回されている影響の可能性が高く、3.x固有かは未切り分けのまま。

## connectWifi()にWiFi.setAutoReconnect(false)を入れ、修正を確認した

`main.cpp`・`piezo_main.cpp`双方の`connectWifi()`（`WiFi.begin()`の直前）に
`WiFi.setAutoReconnect(false)`を追加。2.x（`espressif32@7.0.1`）・3.x
（pioarduino）双方でコンパイルSUCCESSを確認した上でテスト機へ書き込み、
60秒間の観察で`HANDSHAKE_TIMEOUT`ループが**再発しないことを確認**——WiFi再接続の
不具合はこれで解消できたと言ってよい。

（この過程で、pioarduinoのインストールが公式platformの既定解決先を再度上書きする
同じ事故をもう一度踏んだ。復旧手順は前回と同じ。**この事故はコンパイル検証の
たびに再発しうる**——本番envのバージョンpin化(TODO参照)を先送りするほど
踏みやすい。）

## 実機で本題のバグを再現した——3.xで直っていない可能性

WiFi修正確認後、ユーザーの手元でTFTが"NAMAZU"スプラッシュのまま固まった
（`main.cpp`の`samplingTask`作成失敗時の意図的な`for(;;) halt`——安全機構であり
文鎮化ではない）。リセットボタンが反応しなかったため、pyserialでRTS/DTR経由の
ソフトリセットを代行。**その再起動直後のログに以下が出た**:

```
assert failed: udp_new_ip_type /IDF/components/lwip/lwip/src/core/udp.c:1278
(Required to lock TCPIP core functionality!)
...
[coredump] found hardware coredump: 24228 bytes
[coredump] copied to /coredump/0000000041.bin (24228 bytes)
...
[coredump] uploaded and removed /coredump/0000000041.bin (200)
```

**これはPR#191で追ってきたのと同種のバグ**——lwIPのTCPIP専用ロックを持たずに
UDP内部関数（DNS解決がUDP PCBを確保する時に通る`udp_new_ip_type`）を呼んでいる。
PR#191の見立てでは「3.x系(NetworkManager化)でのみ修正済み」だったはずだが、
**実機では起動後10〜15秒以内・2回連続の再起動でこれを踏んだ**——本番2.x機での
発生頻度（数週間に1回程度）よりはるかに高頻度。しかもPR#191で見た「NULL参照
（黙って壊れる）」ではなく、今回は**明示的なassert（即座にpanic→reboot）**という
違う壊れ方をしている。

coredump自動回収パイプライン自体は3.x環境でも正しく機能した（収穫）。ただし
**「3.x移行がPR#191のクラッシュを根治する」という当初の前提は、この1回の観測
だけでは支持できない**——むしろ逆（直っていない、あるいは別の形でより踏みやすく
なっている）可能性がある。symbolizeして正確な発生箇所・呼び出し元スレッドを
特定するまでは結論を出せない。1回の観測に基づいて「3.xでも直っていない」と
断定するのも早計だが、少なくとも「移行すれば直る」と楽観視できる材料ではない。

## symbolize結果: 3.x固有の新種バグと特定できた（PR#191とは別物）

`coredump/4294967295/fd1b81a-dirty-00001788251351517137.bin`をS3
（`namazu-data-486414336274`バケット。firmware/README.mdが指すのは
`namazu-dashboard-...`だが、coredump自動送信の実際の保存先はdataバケット側
——READMEの例示が古い可能性、要確認）から取得し、この時ちょうど手元に残っていた
実体の`.pio/build/pioarduino-fake-sensor/firmware.elf`（再ビルドではなく実際に
焼いたのと同一バイナリ）で`esp-coredump info_corefile --core-format raw`
（pioarduinoの`xtensa-esp-elf-gdb`使用）を実行——フレーム破壊のない綺麗な
バックトレースが取れた。

```
uploaderTask [main.cpp:657]
→ Uploader::pump → Uploader::postBatch [batch-uplink Uploader.cpp]
→ HTTPClient::POST → HTTPClient::sendRequest → HTTPClient::connect
→ NetworkClientSecure::connect
→ NetworkManager::hostByName() [NetworkManager.cpp:84] ★ここ
→ dns_clear_cache()
→ （保留中だったSNTPの"pool.ntp.org"問い合わせの完了コールバックへ再入）
→ sntp_dns_found → sntp_try_next_server → sntp_request
→ dns_gethostbyname → dns_enqueue → dns_alloc_pcb → dns_alloc_random_port
→ udp_new_ip_type → assert（TCPIPスレッドロックが無い）
```

`NetworkManager::hostByName()`（arduino-esp32 3.x、`framework-arduinoespressif32/
libraries/Network/src/NetworkManager.cpp:84`）自身が、IPv4/IPv6のグローバル
アドレス有無が前回呼び出しから変化した時に`dns_clear_cache()`というlwIP内部
関数を**TCPIPスレッドへ委譲せず直接呼んでいる**。この関数は単なるキャッシュ
クリアではなく、保留中の全DNS問い合わせのコールバックをその場で同期的に叩く
実装で、今回はたまたま裏で進行中だったSNTPの"pool.ntp.org"問い合わせの完了処理に
再入し、そこが新規UDP確保をしようとしてassertに落ちた。

`hasGlobalV4`/`hasGlobalV6`はstatic変数で初期値`false`なので、**WiFi接続後に
`hostByName()`が最初に呼ばれた瞬間、ほぼ確実にこの分岐へ入る**——起動後10〜15秒
・2回連続で踏んだ理由はこれで説明がつく。

**PR#191（2.x系）の`WiFiGeneric::hostByName()`が`dns_gethostbyname()`を直接
呼ぶ問題とは別物の、3.x系の`NetworkManager::hostByName()`固有の新しいバグ。**
2.x側は「稀にしか起きないスレッド競合レース」だったのに対し、こちらは条件が
揃えば起動直後にほぼ決定論的に踏む——**3.x系の方がむしろ踏みやすい、別種の
同カテゴリ(lwIP thread-safety違反)バグ**。espressif/arduino-esp32のGitHub
issueに同種の報告が無いか確認する価値はあるが、今回のPoCではそこまで手を
広げていない。

## 結論（初版）

**「arduino-esp32 3.xへ移行すればPR#191のクラッシュが根治する」という当初の
前提は、実機検証の結果誤りだったと判断できる。** 3.x系は別の、しかもより
高頻度で踏みやすいlwIP thread-safety違反を新たに抱えている。この特定のバグは
arduino-esp32本体（`NetworkManager.cpp`）側の実装に起因するため、自前コードの
修正では直せない——上流の修正を待つか、`hostByName()`を呼ぶ経路自体を避ける
（例: 起動直後に安全な文脈で一度だけhostByNameを済ませておく、等）ような
回避策が要る。**この状態で3.x移行を進める積極的な理由は無くなった**——
現状の2.x起因のクラッシュは自動再起動で自己回復しており緊急性が無いことも
含め、**このPoCはここでいったん打ち止めとし、3.x移行は保留にするのが妥当**
という評価に至った。

**（後日追記）上記は`dns_clear_cache()`をローカルパッチで直すまでの暫定結論。
実際に直したところ再現しなくなったため、下の「ローカルパッチで実機検証:
再発しないことを確認」を経て評価を更新した——「結論（更新版）」参照。**

## ローカルパッチで実機検証: 再発しないことを確認

並行して[PR#193](https://github.com/nna774/NamazuHaUrokoGaNai/pull/193)で、
2.x系device2でも`WiFiGenericClass::hostByName()`の同種バグ（[PR#191](https://github.com/nna774/NamazuHaUrokoGaNai/pull/191)参照）が再発していたと判明。
2.x側には既にupstreamの修正が存在すると分かった:
[espressif/arduino-esp32#8672](https://github.com/espressif/arduino-esp32/pull/8672)
（2023-12-05マージ、`dns_gethostbyname()`を`esp_netif_tcpip_exec()`経由で
TCPIPスレッド上に委譲する、1ファイル23行追加の小さな修正）——ただし`release/v2.x`
ブランチには未バックポート。現在インストールされている実際の2.0.17の
`WiFiGeneric.cpp`を確認したところ、この修正がほぼそのまま当たる構造（行番号
まで一致）だった。

ここから「3.x側の`dns_clear_cache()`にも同じ手法（`esp_netif_tcpip_exec()`で
包む）を適用すれば直せるのでは」という発想に至り、`~/.platformio`上の
`framework-arduinoespressif32`(3.3.11)の`NetworkManager.cpp`を直接パッチして
検証した:

```cpp
// hostByName()内、80行目付近
- dns_clear_cache();
+ esp_netif_tcpip_exec(namz_dns_clear_cache_tcpip_ctx, nullptr);
  // namz_dns_clear_cache_tcpip_ctx()はdns_clear_cache()を呼ぶだけのラッパー
  // (esp_netif_tcpip_execが要求するesp_err_t(*)(void*)シグネチャに合わせるため)
```

`pioarduino-fake-sensor`envでビルド・テスト機へ書き込み、**45秒間の観察で
複数回のPOSTリトライ（＝複数回の`hostByName()`呼び出し）を経ても、
`udp_new_ip_type`assert・パニック・再起動が一切発生しないことを確認した**。
POSTが`connection refused`で失敗し続ける件は残っているが、これはクラッシュとは
無関係の別問題（TODO参照、未着手のまま）。

なおこのパッチは`~/.platformio`（プロジェクト外のグローバルパッケージキャッシュ）
への直接編集による**使い捨ての検証**であり、リポジトリには反映されていない。
本採用する場合は`firmware/patches/`への`.patch`ファイル化＋`extra_scripts`での
ビルド時適用（`get_fw_version.py`と同じ仕組み）が必要——次のステップとして
TODOに追加した。

## 結論（更新版）

**「3.xへ移行すればPR#191のクラッシュが根治する」という前提は、`hostByName()`
関数をそのまま使う限りでは誤りだったが、`dns_clear_cache()`呼び出しに
PR#8672と同じ手法の1行パッチを当てれば3.x側も直せる見込みが立った。**
2.x側（`WiFiGeneric.cpp`、PR#8672のバックポート）・3.x側
（`NetworkManager.cpp`、`dns_clear_cache()`の委譲）双方に同種のローカルパッチが
必要になる——**3.x移行を「保留」から「パッチ込みで再検討」に格上げできる状態**。
ただし今回の検証はまだ「使い捨てのローカル編集で45秒間クラッシュしなかった」
段階に留まり、ビルド時パッチとしての本実装・長期観察・2.x側パッチの同等検証は
未着手。

## 事故: 並行セッションと`~/.platformio`の取り合いになった

`dns_clear_cache()`パッチの動作確認を続けていたところ、`espressif32`の既定解決先が
platform=pioarduino(55.3.311)・framework=公式2.0.17という**壊れた組み合わせ**に
なっているのを発見した。このPoCセッションはこの間読み取り専用の操作しかしておらず、
**このマシン上で並行して動いている別セッションが同じグローバルキャッシュを
触っていた**と判断（[PR#193](https://github.com/nna774/NamazuHaUrokoGaNai/pull/193)の
概要欄に「別セッションの`~/.platformio`キャッシュ変更の影響で完全一致が取れなかった」
と書かれていたのは、まさにこちらの過去の作業が向こうを巻き込んでいた証拠）。

これを受け、**グローバルキャッシュへの直接編集による検証はもう安全に続けられない**
と判断し、以降は`firmware/patches/patch_network_manager.py`
（`extra_scripts`でビルド時に自動適用、プロジェクト内で完結・他セッションの状態に
非依存）へ切り替えた。内容は検証済みの`dns_clear_cache()`パッチに加え、DNS解決の
成否・使用中DNSサーバを無条件で出す診断ログを追加したもの。`[env:pioarduino-fake-sensor]`
の`extra_scripts`に追加し、`pioarduino-fake-sensor`env限定（対象ファイルが存在する
時だけ動くので2.x系envには無害）。

## 診断ログでPOST失敗の直接証拠を得た: DNS解決自体が失敗している

```
[namz-dns] hostByName('...lambda-url...') hasV4=1 hasV6=0 dns0=8.8.4.4 dns1=8.8.4.4
[namz-dns] hostByName('...') FAILED err=-54
[NetworkManager.cpp:159] hostByName(): DNS Failed for '...' with error '-54'
```

- **DNS解決は確かに失敗している**（ネットワーク自体というより解決処理側の問題という
  当初の直感が支持された）
- `54`は`lwip/errno.h`上`EXFULL`（"Exchange full"）。lwIPのDNS文脈では典型的に
  **DNSリクエストテーブルが埋まっていて新規登録できない**時に出るコード
  （lwIP本家`netdb.c`の`lwip_getaddrinfo()`はEAI_*系(200番台)しか返さないため、
  ESP-IDF側の実装がこの生のerrno値を返している可能性が高いが、該当ソースの
  正確な特定はできていない）
- これは前段のcoredump symbolizeで見つけた「SNTPの`pool.ntp.org`問い合わせが
  完了せず`dns_clear_cache()`から再入された」という話と直接つながる——この
  問い合わせがずっと片付かずテーブルの枠を専有し続けていれば、後続の
  `hostByName()`が軒並み「テーブル満杯」で即失敗する、という筋が通る
- `dns0=dns1=8.8.4.4`という**両方とも同じGoogle Public DNS**という構成は、
  ユーザーによるとルータのDHCPは`8.8.8.8`/`8.8.4.4`の2つを配っているはずとのことで、
  **期待値と食い違っている**——自前コードにハードコードは無いので、DHCP応答の
  読み取り・保存のどこかでprimary/secondaryの扱いが狂っている可能性がある
- このプロジェクト自体に前例あり（`firmware/src/config.h`のコメント）:
  device2で`maxblock_8bit`が1300〜2000台まで落ちると`DNS Failed`が繰り返し
  起きていた実績（`kMaxRamBatches`を3→2に下げて解消）。今回の観測はそれより
  さらに低い(900〜2500)水準で高止まりしている——ただし`kMaxRamBatches`は
  既に2に設定済みで、この対策だけでは足りていない

## dns0破損のタイミングを特定: connectWifi()直後は正常、timesync::begin()区間で壊れる

`main.cpp`の`connectWifi()`末尾にも診断ログを追加し、リセット直後から捕捉した:

```
[namz-dns] connectWifi() done: dns0=8.8.8.8 dns1=8.8.4.4   ← WiFi接続直後は正しい
...(約5秒後、最初のhostByName呼び出し時)...
[namz-dns] hostByName(...) dns0=8.8.4.4 dns1=8.8.4.4        ← dns0がdns1と同じ値に
```

**DHCPは正しく`8.8.8.8`/`8.8.4.4`を配っている（ユーザーの認識通り）。
`connectWifi()`が返った直後の時点ではまだ正しい値が入っている。** その後
`main.cpp`が呼ぶ`timesync::begin(kNtpServer1="ntp.nict.jp",
kNtpServer2="pool.ntp.org", ...)`（`main.cpp:810`、ESP-IDF標準SNTPクライアント
`esp_sntp_setservername`/`esp_sntp_init`を叩くだけ、DNS設定を直接触るコードは
batch-uplinkの`TimeSync.cpp`には無い）の区間で`dns0`が壊れる。

lwIP本家`dns.c`を読んだ範囲では、個々のDNS問い合わせが失敗時に`server_idx`を
進めてサーバを切り替える仕組みはあるが、グローバルな`dns_servers[]`配列自体を
書き換えるコードは見当たらなかった——つまり内部フォールバックの副作用ではなく、
**ESP-IDF側の別のコードパス（netif/DHCP/SNTP関連のどこか）が
`esp_netif_set_dns_info()`相当を明示的に呼んで上書きしている**可能性が高い。
SNTPが最初に解決しようとする`ntp.nict.jp`（`kNtpServer1`）の解決自体が
このゲストVLANで失敗し、それが何らかの経路で`dns0`破損・DNSテーブル占有
（前段の`err=-54`）の連鎖の起点になっている、というのが今のところ一番有力な仮説。

## 訂正: 「err=-54(EXFULL/テーブル満杯)」説は誤りだった。型不一致バグの産物

ユーザーから「DNSが8.8.4.4だけになったとしても、それだけで引けなくなるのは
おかしい」と指摘を受け、調べ直した。**「EXFULL(テーブル満杯)」説は誤りだった。**

`lwip/err.h`を確認したところ`typedef s8_t err_t;`——`err_t`は符号付き**8bit**
（-128〜127）。一方`NetworkManager::hostByName()`はこの`err_t err`に
`lwip_getaddrinfo()`の戻り値（`EAI_FAIL=202`のような`int`範囲のgetaddrinfo系
コード）をそのまま代入していた。**202は8bit符号付きに収まらず暗黙に切り詰め
られる：`202 - 256 = -54`。** さらに`lwip_getaddrinfo()`自体（ESP-IDF実装、
espressif/esp-lwip@`fd432e4`の`src/api/netdb.c:495-498`で確認）は、内部の
`netconn_gethostbyname_addrtype()`が返す本物の`err_t`を全部`EAI_FAIL`一つに
握りつぶして返す実装になっている。つまり「err=-54」は**DNSリクエストテーブル
満杯を意味しない**——単にこの型不一致バグが生んだ無意味な値だった。

握りつぶされる前の本物の`err_t`を見るため、`NetworkManager.cpp`のパッチに
`netconn_gethostbyname_addrtype()`への診断専用呼び出しを追加し、実機で
再確認した:

```
[namz-dns] hostByName('...') raw netconn_gethostbyname_addrtype err_t=-6
```

**`-6`はlwIPの`ERR_VAL`（"Illegal value"）——今度は8bitに収まる本物の値。**
（この診断呼び出しは追加のDNS問い合わせを発生させるため、WDTを踏んで再起動を
招いた——診断コード自体の副作用であり、本題のバグではない。本採用時は
外すこと。）

## ERR_VALの発生源を`dns_send()`まで追った——プリコンパイル済み領域が壁

`ERR_VAL`を返す箇所はESP-IDF版`dns.c`（`fd432e4`）に2箇所:

1. `dns_gethostbyname_addrtype()`: `dns_server_is_set()`が偽（=`dns_servers[]`
   全部未設定）の時。**該当しない**——診断ログで`dns0=dns1=8.8.4.4`と、
   どちらも有効な値だったことを確認済み
2. **`dns_send()`の`overflow_return:`**（`query_idx + n + 1 > 0xFFFF`という
   u16オーバーフローガード）。こちらが該当する可能性が高い

```c
/* convert hostname into suitable query format. */
query_idx = SIZEOF_DNS_HDR;
do {
  ...
  for (n = 0; *hostname != '.' && *hostname != 0; ++hostname) { ++n; }
  copy_len = (u16_t)(hostname - hostname_part);
  if (query_idx + n + 1 > 0xFFFF) {
    /* u16_t overflow */
    goto overflow_return;   // ← ERR_VAL(-6)
  }
  ...
} while (*hostname != 0);
```

うちが解決しようとしているホスト名（`5uglpx52w3n7ktm3clomjt5rfa0nmocn.lambda-url.ap-northeast-1.on.aws`、約66文字）で
このガードに正常に引っかかることは**あり得ない**（65535を大きく下回る）。
`pbuf_alloc()`失敗（ヒープ枯渇）は別の`ERR_MEM`経路になるので、これも除外できる
（コード上、`if (p != NULL) {...} else { err = ERR_MEM; }`と分岐している）。

**ここが今回の調査の到達点。** このガードが正常なホスト名長で引っかかるという
ことは、`entry->name`（DNSテーブルエントリに格納されたホスト名文字列）自体が
壊れている・終端が壊れて読み過ぎている、というのが最も筋の通る説明——
**ユーザーの「中身が破壊されまくってるのでは」という直感を支持する結果**に
なった。ただし`dns_send()`・`dns_table[]`は`liblwip.a`にプリコンパイル済みの
領域で、今のソーステキストパッチ方式（Arduinoレイヤーの`.cpp`だけを書き換える）
ではこれ以上覗けない——完全な再検証にはESP-IDFのlwipコンポーネントを自前で
再ビルドするか、JTAG等での実機ライブデバッグが要る。今回のPoCの範囲としては
一旦ここで打ち止めが妥当。

## coredump形式の制約でdns_table[]は読めないと判明、生メモリダンプ診断へ切り替え

前段のcoredump（symbolize済み、実は`netconn_gethostbyname_addrtype`診断呼び出し
自体がWDTを誘発したもの）で`dns_table`（nmで判明したアドレス`0x3ffc9310`）を
GDBで直接覗こうとしたところ、**そもそもESP32既定のcoredump形式には各タスクの
スタック/TCBしか含まれず、`dns_table`のようなグローバル変数(BSS/DRAM)は
対象外**と判明した（`.coredump.tasks.data`セグメント一覧に該当アドレスが
無いことで確認）。JTAGでのライブデバッグなら生メモリを直接読めるが手元に無い。

代わりに、`hostByName()`失敗の瞬間に`dns_table`/`dns_pcbs`の生バイトを
`Serial.printf`で直接ダンプする診断コードを`patch_network_manager.py`に追加した
（シンボルではなく既知の固定アドレスへの直接キャストで読む、リビルドの
たびにnmで再確認が必要）。危険な`netconn_gethostbyname_addrtype`診断呼び出し
（WDT誘発の原因、目的は達成済み）はここで撤去した。

なお`esp-coredump`のSHA256不一致チェックは今回も再発した（ビルドごとに
`app_elf_sha256`フィールドだけが変わる既知の癖、PR#191の時と同じ）。
`.venv`本体を書き換える権限は無かった（worktree保護）ため、job tmpへ
`esp_coredump`パッケージをコピーしてその場でモンキーパッチし、
`PYTHONPATH`で差し替えて実行する方式で回避した——`.venv`は無傷のまま。

## 新しいクラッシュ発見: heap枯渇によるfopen()内lock初期化失敗

上記の診断コードを仕込んで再度実機確認したところ、**今回は`hostByName()`が
2回とも成功した**（`54.168.221.225`→再起動後`52.69.247.194`）——DNSは常に
失敗するわけではなく、`dns0=dns1=8.8.4.4`のままでも解決できる時はできる
（ユーザーの「それだけで引けなくなるのはおかしい」という指摘とも整合する）。
ただしDNS成功後もTCP接続が`select()`タイムアウトで失敗する場合があった。

さらに直後、**DNSとは無関係の新種のクラッシュ**が発生し、自動アップロード
済みのcoredumpをsymbolizeして特定した:

```
Uploader::oldestQueuedStartUs → Uploader::loadOldestSpillPath
  (batch-uplink Uploader.cpp、spillの中で一番古いファイルを探す)
→ fs::File::openNextFile → VFSFileImpl::openNextFile → fopen()
→ _fopen_r() → __sfp()（newlib、新しいFILE構造体確保）
→ __retarget_lock_init_recursive() → lock_init_generic()
→ abort()（newlib locks.c:77、ロック用mutexの確保に失敗すると即abort()する実装）
```

このタイミングで**spillファイルが184個**溜まっていた（`spill files on boot: 184`）
——POSTが継続的に失敗し続けているせいで送れなかったバッチが延々と積み上がって
いる状態。`loadOldestSpillPath()`はLittleFSのディレクトリを`openNextFile()`で
辿るが、その内部で新しい`FILE*`用のロックをFreeRTOSミューテックスとして確保
しようとして、**ヒープが確保に足りず即abort()**——DNSの一連の問題とは別に、
**このビルド構成では一般的なヒープ枯渇に対する耐性自体が低い**ことを示す
新しい証拠。`maxblock_8bit`がずっと900〜2500byte台で高止まりしている状態と
符合する。

「DNS失敗→spill蓄積→ヒープ圧迫→別のクラッシュ」という悪循環になっている
可能性が高い——DNS/dns_table自体の破損を追うだけでなく、根本のヒープ余裕
（TLS専用プール確保後の残り約90KB強で、そこからさらにbatchバッファプール
54KB・spillの都度確保が食い合っている構図）自体を見直す必要があるかもしれない。

## maxblock_8bit崩壊の犯人を特定: 2.x/3.xの差ではなく、spill蓄積によるO(n)ディレクトリ走査

`setup()`の要所に`heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)`の打点
（`NAMZ_HEAP_CHECKPOINT`、docs/log記載後に取り除くローカル診断）を追加し、
実機で計測した:

```
setup直後:              free=259236  maxblock_8bit=110580
tlsmempool後:            free=203936  maxblock_8bit=110580  (TLSプール52KBはmaxblock無影響)
setupBatchPool後:        free=146480  maxblock_8bit= 57332  (batchプール54KB、想定通り)
connectWifi後:           free= 92912  maxblock_8bit= 51188  (WiFi/lwIP初期化、軽微)
timesync::begin後:       free= 92888  maxblock_8bit= 51188  (ほぼ無変化)
coredump drain後:        free= 92784  maxblock_8bit= 51188  (実TLS/HTTPS往復1回でも断片化ゼロ)
Uploader::begin()後:     free= 70112  maxblock_8bit= 27636  (-23.5KB、まだ通信前なのに激減)
最初のspill読込直後:                  maxblock_8bit=  1012  (さらに壊滅的)
```

**犯人は`Uploader::begin()`と`loadOldestSpillPath()`（batch-uplink
`Uploader.cpp`）——どちらも溜まった退避ファイルをLittleFSの`openNextFile()`で
1件ずつ列挙するO(n)スキャン。** `begin()`は起動時に退避数を数えるため184件
全部を、`loadOldestSpillPath()`は**pumpサイクルのたびに毎回**184件を舐めて
最古のファイルを探す（ソート済みインデックス等は無く、毎回ゼロから
ディレクトリを辿る実装）。`openNextFile()`はArduino-ESP32のFS実装内部で
`std::make_shared<VFSFileImpl>`を使っており、ファイル1個の開閉のたびに
ヒープ確保・解放が走る——これが184回×毎pumpサイクルで積み重なり、
一般ヒープを激しく断片化させていた。

**このコードパス自体は2.x/3.xで同一**（`std::make_shared<VFSFileImpl>`は
2.xの`vfs_api.cpp`にも同一実装で存在すると確認済み、上の「訂正」節参照）。
既にコード側にも「ヒープ極度逼迫時に`std::bad_alloc`相当の未捕捉例外→
`abort()`で再起動する」ことを把握した上での`try/catch`ガードが入っている
（クラッシュ自体は防ぐが、断片化そのものは防げない設計）。

**つまり「2.x/3.xのアーキテクチャ差」という当初の見立てより、以下の悪循環
の方が実態に近い:**

```
3.x固有のDNS/TCP接続系バグ（dns_clear_cache thread bug[修正済]・
断続的なERR_VAL失敗・TCP connectタイムアウト）
  → POST失敗が続く → spillファイルが蓄積(184件)
  → begin()/loadOldestSpillPath()のO(n)スキャンが毎回重くなる
  → ヒープが激しく断片化(maxblock_8bit低下)
  → fopen()等の新規小確保が失敗しやすくなる → 別のクラッシュ・失敗を誘発
  → さらにspillが溜まる（自己強化）
```

健全にPOSTが成功し続けている状態ならspillはほぼ0件で保たれ、このスキャン
コストは無視できる規模のはず——**今観測している深刻な断片化は、3.xの
DNSバグ由来の失敗の蓄積が引き金になった二次的な症状**という理解に至った。

## batch-uplinkに退避ファイル列挙の軽量化PRを出した

犯人（`Uploader::begin()`/`loadOldestSpillPath()`のO(n)ディレクトリスキャン）
への対処として、ユーザーと相談の上で以下の方針に決めた:

1. `File`/`openNextFile()`（エントリごとに重い`std::make_shared<VFSFileImpl>`
   を確保する）を、POSIXの`opendir`/`readdir`（軽量、ヒープ確保無し）へ置き換える
2. `loadOldestSpillPath()`の「全件比較して厳密な最古を探す」実装自体を撤去し、
   「`readdir()`が返す最初の非ディレクトリエントリをそのまま使う」に単純化する
   ——この関数が実際に保証すべきなのは厳密な最古優先ではなく「新しいデータの
   流入で古いバックログが飢餓しないこと」だけで、データ自体にタイムスタンプが
   埋め込まれているため配送順の厳密さは下流の正しさに影響しない、という
   ユーザーの指摘に基づく判断。`dropOldestWhenFull=true`のeviction対象も
   同様に「既存の退避ファイル群のいずれか」になるが、捨てる対象は元々RAMキュー
   より新しいデータより古い(spill済みの)ものに限られるため、「最新のRAMキュー
   データを優先して残す」という本来の狙いは変わらない

[nna774/batch-uplink#29](https://github.com/nna774/batch-uplink/pull/29)として
実装・提出した（未マージ、Electabuzzは配送順に依存していないとユーザーに確認
済み）。`esp32dev`（2.x、公式platform）・`pioarduino-fake-sensor`（3.x）双方で
ローカルに取り込んでコンパイル成功を確認したが、**実機での断片化改善効果の
実測はまだ行っていない**。

## TODO

- [x] ~~`udp_new_ip_type`assertのcoredumpをsymbolizeし、PR#191と同じ呼び出し
      経路かを特定する。~~ → 完了。**PR#191とは別物、`NetworkManager::hostByName()`
      内の`dns_clear_cache()`起因の3.x固有バグと判明。**
- [x] `connectWifi()`（`main.cpp`・`piezo_main.cpp`）に3.x系向けの対処
      （`WiFi.setAutoReconnect(false)`）を入れて実機で確認した——解消を確認済み。
      （3.x移行自体を保留する場合でも、この変更は2.x側にも実害が無く残して良い）
- [x] `dns_clear_cache()`パッチを`firmware/patches/patch_network_manager.py`
      （`extra_scripts`でビルド時自動適用）として本実装した。DNS解決の診断ログも
      同時に追加、実機で動作確認済み。
- [x] ~~`netconn_gethostbyname_addrtype()`への診断専用呼び出しを取り除く。~~ →
      完了。目的（生の`err_t`確認）を達成後に撤去し、代わりに`dns_table`等の
      生バイトダンプ診断へ差し替えた。
- [x] **`main.cpp`の`NAMZ_HEAP_CHECKPOINT`診断で`maxblock_8bit`崩壊の犯人を
      特定した** → 完了、上の節参照。`Uploader::begin()`/`loadOldestSpillPath()`
      （batch-uplink）のO(n)ディレクトリスキャンが原因で、2.x/3.xのコード自体は
      同一——3.xのDNSバグ由来の失敗蓄積が引き金になった二次的な症状と判断。
- [ ] **`main.cpp`の`NAMZ_HEAP_CHECKPOINT`診断（6箇所）を本採用前に取り除く
      こと。** 調査用途のみ。
- [x] ~~batch-uplink側の改善案（`loadOldestSpillPath()`のO(n)スキャン軽減）~~
      → 完了、実装・提出済み。**[batch-uplink#29](https://github.com/nna774/batch-uplink/pull/29)**
      （`opendir`/`readdir`への置き換え＋全件比較の撤去）。未マージ。
- [ ] batch-uplink#29マージ後、実機（大量のspill滞留状態）で断片化改善効果を
      実測する——今はコンパイル確認のみ。
- [x] `dns0=dns1=8.8.4.4`になるタイミングを切り分けた → 完了、下記参照。
      **`connectWifi()`直後は正しい(`8.8.8.8`/`8.8.4.4`)、`timesync::begin()`の
      区間で壊れる。**
- [x] ~~`err=-54`(EXFULL)が本当に「DNSリクエストテーブル満杯」を意味するか
      裏付ける。~~ → **訂正して完了**。EXFULL説は誤りで、`err_t`(8bit)への
      `EAI_FAIL`(202)代入による型不一致の切り詰めが原因と判明
      （「訂正: 「err=-54」説は誤りだった」節参照）。本物の値は`ERR_VAL`(-6)。
- [x] `timesync::begin()`区間で`dns0`が壊れる原因を追った → **`dns_send()`の
      `overflow_return:`(u16オーバーフローガード)がERR_VAL(-6)の発生源と特定**
      （「ERR_VALの発生源を`dns_send()`まで追った」節参照）。約66文字の
      ホスト名で正常にこのガードへ引っかかることはあり得ず、DNSテーブル
      エントリ(`entry->name`)自体の破損を疑う根拠になった。ただし`dns_send()`
      は`liblwip.a`にプリコンパイル済みでこれ以上パッチできず、**今回のPoCの
      範囲としてはここが調査の到達点**。
- [x] coredumpから`dns_table`を直接読めるか試した → **不可と判明**（タスクの
      スタック/TCBしか含まれない、ESP32既定のcoredump形式の制約）。代わりに
      `hostByName()`失敗時に生バイトをSerial出力する診断へ切り替えた
      （「coredump形式の制約で...」節参照）。まだ失敗ケースを捕まえられて
      いない——DNSは常に失敗するわけではなく成功する時もあると判明したため。
- [ ] **最優先: 上記の生バイトダンプで実際に`hostByName()`失敗を捕まえて
      `dns_table`/`dns_pcbs`の中身を見る。** DNSは決定論的に毎回失敗する
      わけではないと分かった（今回はconnectWifi後2回とも成功）——再現条件が
      当初の想定より曖昧になっている。
- [ ] **新規: `fopen()`内部のnewlibロック初期化失敗によるabort()を発見した**
      （「新しいクラッシュ発見: heap枯渇によるfopen()内lock初期化失敗」節参照）。
      `Uploader::loadOldestSpillPath()`がspill(184件溜まっていた)を
      `openNextFile()`で辿る際、新規`FILE*`のミューテックス確保に失敗して
      即abort()。DNS系の問題とは別の、**ヒープ全般の枯渇耐性の低さ**を示す
      証拠——「DNS失敗→spill蓄積→ヒープ圧迫→別クラッシュ」の悪循環を疑う。
      TLS専用プール確保後の残りヒープ配分（batchバッファプール54KB等との
      食い合い）自体を見直す必要があるかもしれない。
- [ ] `dns0`破損が`timesync::begin()`の**どの内部処理**(SNTPの`ntp.nict.jp`
      解決失敗？)によって引き起こされているかは、上記の壁により未特定のまま。
- [ ] 2.x側パッチ（`WiFiGeneric.cpp`、PR#8672バックポート）はまだ
      `firmware/patches/`化していない・実機検証もしていない——device2で再発した
      本題はこちら。
- [ ] 3.x側パッチ込みでの長期観察（TFT・OTA・coredump・WDT・spillまわり）は
      まだ未実施——今回は短時間確認のみ。
- [ ] **本番env(`esp32dev`・`adxl355`とその派生)の`platform`行をバージョン明示pin
      するか検討する**（名前衝突事故の再発防止策。今回もこの事故を再度踏んだ
      ——検証のたびに再発しうるので優先度を上げてよいかもしれない。3.x移行を
      保留する場合でも、pioarduino-fake-sensor envを今後も使う限り関係が残る）。
- [ ] LittleFSの`Unable to allocate FD`が3.x固有か、この基板の使い回し影響かは
      未切り分けのまま（優先度は下がった）。
- [x] ~~`NetworkManager::hostByName()`のバグがespressif/arduino-esp32側で
      既知issueになっているか確認する。~~ → 完了、下記参照。

### 上流issue調査: 完全一致は無いが、同カテゴリの再発バグと確認できた

`gh issue list --repo espressif/arduino-esp32 --search "..."`で
`"Required to lock TCPIP core functionality"`検索。**`NetworkManager::hostByName()`
→`dns_clear_cache()`→SNTP再入という今回の経路そのものを報告しているissueは
見つからなかった**（＝おそらく未報告の具体的な経路）が、「TCPIPロック無しで
lwIP内部関数を呼んでassert」というカテゴリ自体は繰り返し報告されている既知パターン
だった:

- [#10675](https://github.com/espressif/arduino-esp32/issues/10675)
  `assert failed: sntp_stop ...` — SNTP絡み。v3.1.0で一度
  [PR#10725](https://github.com/espressif/arduino-esp32/pull/10725)により修正
  （`configTzTime()`二重呼び出しのケース）
- [#10781](https://github.com/espressif/arduino-esp32/issues/10781)
  `assert failed: tcp_alloc ...` — 別経路（AsyncTCP）で同種
- [#10526](https://github.com/espressif/arduino-esp32/issues/10526)
  同エラーメッセージ、3.1.0-RC2で新規発生と報告
- [#12769](https://github.com/espressif/arduino-esp32/issues/12769)
  （**2026-08-06クローズ、直近**）HTTPS POST + SNTPがらみで同種のTCPIPロック
  assertを報告。`esp_sntp_stop()`を呼んでも直らないと書かれているが、報告者は
  最終的に「うちのタスクのメモリ確保ミスだった、core側の欠陥ではなかった」と
  自己解決でクローズしており、core側の欠陥として確定はしていない

**v3.1.0で一部（`configTzTime`二重呼びのケース）は直ったが、「TCPIPロック無しで
lwIPに触る」というカテゴリのバグは3.3.10/3.3.11時点（うちが検証した版）でも
根絶されていない**。うちが踏んだ`dns_clear_cache()`経由の経路は、少なくとも
検索した範囲では未報告——上流にissueを立てる価値はあるが、今回のPoCの範囲では
未実施。
