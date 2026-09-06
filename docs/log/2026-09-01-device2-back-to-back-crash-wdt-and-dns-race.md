# device2、起動直後に2連続クラッシュ——TASK_WDT(TLSハンドシェイク待ち)とdevice1と同じdns_pcbレースが立て続けに発生

`coredump/0002/70ae824-00001788251434943080.bin`・`70ae824-00001788251436056891.bin`
（S3、2026-09-01 17:30:34/36アップロード、1.1秒差）を調査した。`GET /devices/0002`では
`fw_version: 70ae824`(OTA無し、現行稼働版と一致)・`reset_reason: PANIC`・
`boot_epoch_us`が17:30:17——**この起動そのものが2件のcoredumpの発生源**（前回起動までに
2回連続でクラッシュし、3回目でようやく安定して起動、その直後にキュー内の2件を
まとめてアップロードした)と判断できた。

## シンボライズ手順で踏んだ落とし穴: 並行セッションのPlatformIOキャッシュ汚染

`70ae824`はOTA配信時刻(2026-08-31 01:43)が`.elf`保存機能のmerge(同日02:05)より前で、
S3に`.elf`が無い版——[firmware/README.md](../../firmware/README.md#クラッシュ後のcoredump吸い出し)
の旧手順(detached worktreeで再ビルド)が必要だった。ところが同じマシン上で並行して
走っていた別セッション([2026-09-01-pioarduino-arduino3-poc.md](2026-09-01-pioarduino-arduino3-poc.md))が
arduino-esp32 3.x移行PoCのため`~/.platformio`の共有プラットフォームキャッシュを
複数回上書き・復旧しており、素の`pio run -e adxl355`が`platform = espressif32`
(バージョン無指定)を経由して意図せず3.x系(pioarduino)を掴み`'WiFi' was not declared`で
ビルド落ちした。`platform = espressif32@7.0.1`を明示pinして回避した。

ビルドは成功したが、S3の`ota/adxl355/70ae824.bin`と`cmp -l`で照合したところ
**243,525バイト(全体の23%)が不一致**——過去の成功事例(32〜65バイトのみ、`app_elf_sha256`欄と
末尾チェックサム)とは桁違いで、コード実体レベルで再現できていないと判明した。
`toolchain-xtensa-esp32@8.4.0+2021r2-patch5`自体は7月から不変で無関係、原因は
`framework-arduinoespressif32`側(バージョン範囲`~3.20017.0`の中でのマイナーな解決差、
または今回のpioarduino事故の復旧で当日中にパッケージが再インストールされたこと)に
あると見られるが特定はできなかった。**バイト完全一致でのシンボル解決保証は今回は
得られていない。**

それでも`esp-coredump`のSHA256不一致チェックをモンキーパッチで警告に格下げして
読み進めたところ、**2件とも綺麗に(「optimized out」の連鎖や矛盾した呼び出し関係の
無い)一貫したバックトレースが得られ**、かつ下記の通りいずれも既知パターンと
（後述のarduino-esp32#9388は他ハードウェアのレジスタ値とも）一致した。この一致自体が
「エントリポイント付近のコード配置は今回のビルドでも実機とほぼ同一だった」ことの
状況証拠にはなるが、**フレーム1以降の細部（特にcrash 1のuploaderTask側)は保険的に
「大筋は合っているはず」程度の信頼度で読むべき**、という留保付きで以下に記録する。

## crash 1(先に発生・先にアップロード): 既知のTASK_WDT/TLSハンドシェイク待ち

```
task_wdt_isr → abort()（TASK_WDTパニック）
crashed context: IDLE0（WDT ISR由来のためこう出る。実際に詰まっていたのは'uploader'）

'uploader'タスク:
  uploaderTask (main.cpp:651)
  → Uploader::pump → Uploader::postBatch (Uploader.cpp:395)
  → HTTPClient::POST → sendRequest → connect
  → WiFiClientSecure::connect(ip, port, host, ...)
  → start_ssl_client (ssl_client.cpp:277、vTaskDelay(2)のハンドシェイク待ちループ)
```

[2026-08-29](2026-08-29-device2-task-wdt-coredump-tls-handshake.md)・
[2026-08-31](2026-08-31-device2-ota-pull-wdt-panic.md)で確認済みの「TLSハンドシェイク待ちが
WDTの20秒に届く」パターンと同型。`docs/design.md`「ネットワークI/Oのタイムアウト予算」に
既に記録済みの**未解決の既知制限**（`setHandshakeTimeout()`はmbedtls_ssl_handshake()
呼び出し間にしか効かず、個々のsocket recv()一発の詰まりは防げない）がまた発現した、
という以上の新情報ではない。

## crash 2(1回目のリブート直後・2回目にアップロード): device1と同一のdns_pcbレース

```
Crashed task: 'tiT'（lwIP tcpip_thread）
exccause: 0x1c (LoadProhibitedCause)
excvaddr: 0x15
pc: udp_sendto+31 (udp.c:540)、pcb=0x1

dns_tmr → dns_check_entries → dns_check_entry → dns_send (dns.c:921) → udp_sendto
```

**exccause・excvaddr・pcb=1・呼び出し経路すべてが、today同日に調査済みのdevice1の2件目
coredump([2026-09-01-device1-udp-sendto-null-deref-coredump.md](2026-09-01-device1-udp-sendto-null-deref-coredump.md))
と完全一致。** あちらで既に特定済みの通り、根本原因は`WiFiGenericClass::hostByName()`
(`WiFiGeneric.cpp:1574`)がlwIPの「DNS関数はtcpip_threadからのみ呼べ」という契約を破って
生API`dns_gethostbyname()`を`uploaderTask`(優先度1・core0)から直接呼んでおり、
`LWIP_TCPIP_CORE_LOCKING`無効なこのビルドでは`tiT`(優先度18・同じcore0)にpreemptされた
瞬間の`dns_table[]`/`dns_pcbs[]`書きかけ状態を読んでしまう——外部の既知issue
[espressif/arduino-esp32#9388](https://github.com/espressif/arduino-esp32/issues/9388)の
レジスタダンプ(`pcb=1`・`EXCCAUSE=0x1c`・`EXCVADDR=0x15`)とも一致する再現性のあるロジック
バグで、修正PR[#8672](https://github.com/espressif/arduino-esp32/pull/8672)はarduino-esp32
3.x系列(`NetworkManager`書き直し)限定、うちが使う2.x系列(EOL)には未反映。

**新情報は「device1固有の偶発事故ではなく、2.x系列を使う自機2台のうち両方で発生した」
という点**——device1は2026-08-31・09-01の3週間で2回、device2は今回が初観測。
`hostByName()`とtcpip_threadの優先度配置(`tiT`優先度18 vs `uploaderTask`優先度1、
両方core0固定)はdevice1・device2で共通の設計のため、**このレースはハードウェア固有ではなく
firmware全体(2.x系列を使う限り)に共通する系統的リスク**と確定できる。

## この2件がなぜ連続したか: 起動直後の再接続がどちらも踏みやすい窓

crash1(TLSハンドシェイク待ち)・crash2(DNS thread race)は表面上は別バグだが、
**どちらも起動直後〜WiFi再接続直後のネットワークI/O集中区間で踏まれている**という
共通点がある。ユーザーの「wifiの不調のタイミングと関係あるかも」という見立ては、
個々のバグの引き金という意味では的確——crash1はTLSハンドシェイクという通信品質に
敏感な区間、crash2は`dns_enqueue()`の再割り当て経路(DNSキャッシュ切れ後の再問い合わせ)
という、いずれもWiFi再接続直後にまとまって起きやすい処理に該当する。ただし
**「WiFiが不調だったから」がcrash2の直接因ではない**——device1側の調査で確定した通り、
crash2は`tiT`によるpreemptionタイミングのレースが本質で、電波状況そのものは
発生条件に含まれない(電波が良くてもDNS再問い合わせのたびに一定確率で踏みうる)。

## 現状の評価

device2は現在`70ae824`・`reset_reason: PANIC`(直近の3回目起動)・`online: true`で
安定稼働中(この調査時点で起動から5分以上経過、正常送信継続)。**crash1(TLSハンドシェイク
WDT)・crash2(dns_pcbレース)いずれも既知の未解決issue**で、今回は「device2でも両方の
発現を実機で確認できた」以上の新しい対処方針は無い。修正手段の評価は両方とも
[2026-09-01-device1-udp-sendto-null-deref-coredump.md](2026-09-01-device1-udp-sendto-null-deref-coredump.md)
「現状の評価」節・`docs/design.md`「ネットワークI/Oのタイムアウト予算」に集約済みなので
ここでは繰り返さない。arduino-esp32 3.x移行の実現性PoC
([2026-09-01-pioarduino-arduino3-poc.md](2026-09-01-pioarduino-arduino3-poc.md))は
「3.x移行してもdns_pcbレースは直るが、3.x固有の別のlwIPスレッド安全性バグ
(`NetworkManager::hostByName()`内`dns_clear_cache()`)を新たに踏む」と結論しており、
移行は保留中——crash2の根治見込みは現時点で無い。

## 次に何が可能になったか

- **同じ日に発生した「別々に見えるcoredump」を、既に同日調査済みの他device分の記録と
  照合するだけで大部分を再利用でき、シンボライズさえできれば深掘りをゼロから
  やり直す必要がないと分かった。**
- **PlatformIOの共有プラットフォームキャッシュ(`~/.platformio`)は複数セッション間で
  競合しうる不安定な状態になりうると実地で確認した。** `firmware/platformio.ini`の
  本番env(`esp32dev`・`adxl355`とその派生)は`platform = espressif32`のままバージョン
  無指定——[2026-09-01-pioarduino-arduino3-poc.md](2026-09-01-pioarduino-arduino3-poc.md)の
  TODOで指摘済みの「バージョン明示pin化」が未着手のままだと、coredump調査のたびに
  同じ再現性リスクを踏む。優先度を上げる材料が今回また一つ増えた。
