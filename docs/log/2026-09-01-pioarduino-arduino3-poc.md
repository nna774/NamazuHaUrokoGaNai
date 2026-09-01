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
- [ ] **最優先: `dns0=dns1=8.8.4.4`（期待値は`8.8.8.8`/`8.8.4.4`の2種）になる原因を
      特定する。** `connectWifi()`直後（WiFi接続直後、DHCP完了直後）の時点でも
      同じ値になっているか、それとも再接続を経るうちにこうなるのかを切り分ける
      診断ログを追加して確認する。
- [ ] `err=-54`(EXFULL)が本当に「DNSリクエストテーブル満杯」を意味するか、
      ESP-IDF側の該当ソースで正確に裏付ける（今は状況証拠のみ）。
- [ ] SNTPの`pool.ntp.org`問い合わせがなぜ完了しない（≒テーブルに居座り続ける）のか
      を確認する——これが本当の根っこの可能性がある。
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
