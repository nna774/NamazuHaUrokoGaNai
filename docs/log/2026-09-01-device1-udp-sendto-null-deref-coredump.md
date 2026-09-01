# device1、`e82f81e`稼働中に2件目のcoredump——今度はラベルが実クラッシュ時期と一致

`coredump/0001/e82f81e-00001788239108678687.bin`（S3、2026-09-01 14:05アップロード）を
シンボライズした。前回([2026-08-31-device1-lwip-null-deref-coredump.md](2026-08-31-device1-lwip-null-deref-coredump.md))
の`...835888345.bin`とはS3キーのタイムスタンプが別で、`cmp -l`でも20868バイト中7076バイトが
異なる——同一ファイルの再送ではなく別クラッシュだった。

## 結果: 今回はラベルが実クラッシュ時期と一致した

前回の教訓（fw_versionラベルを鵜呑みにしない）に従い、まず`GET /devices/0001`で
現在の`reset_reason`/`uptime_s`を確認したところ`PANIC`・起動約59分前で、coredumpの
アップロード時刻（ブート直後）と辻褄が合った——**今回の再起動そのものがこのcoredumpの
発生源**と判断できたため、全履歴照合の前にラベル自身の版を先に疑った。実際、coredump内の
`app_elf_sha256`(`654194662fad9ff6...`)はS3の`ota/esp32dev/e82f81e.bin`のハッシュと
完全一致し、全履歴探索は不要だった。

シンボライズ自体は前回と同じ手順（[firmware/README.md](../../firmware/README.md#クラッシュ後のcoredump吸い出し)）
で、`e82f81e`を手元でdetached worktree再ビルドし、S3の`.bin`と`cmp -l`で照合
（差分65バイト＝`app_elf_sha256`欄32バイト＋末尾チェックサム、既知のパターン）してから
`esp-coredump`にそのelfを渡した。

## クラッシュ内容: 前回と同じexccause/excvaddr、別のlwIP経路

```
Crashed task: 'tiT' (lwIPのTCP/IP内部タスク)
exccause: 0x1c (LoadProhibitedCause)
excvaddr: 0x15
pc: udp_sendto (udp.c:540)、pcb=0x1
```

バックトレース: `dns_tmr → dns_check_entries → dns_check_entry → dns_send → udp_sendto`。
DNS再問い合わせのタイマー経路で、`pcb`に`0x1`という明らかに不正な値が渡っている。
今回はコールチェーンの各フレームが実際に呼び出し関係として成立しており（前回のような
「直接呼べないはずの関数へ飛ぶ」矛盾が無い）、frame 1以降もある程度信用できる。

`exccause=0x1c`・`excvaddr=0x15`は前回のcoredump（`tcp_listen_input`、`5dab9a4`ビルド）と
**完全に同じ値**——`pcb`(=1) + 構造体オフセット(0x14相当)ちょうど`0x15`になる計算が一致して
おり、両者とも「pcbポインタ自体が小さい整数に化けている」同型の壊れ方をしている可能性がある。

## 追調査: これは自前のバグではなく既知の未解決upstreamバグだった

`dns_send()`の実ソース（ESP-IDF 4.4.7が固定するlwIPフォーク、
[espressif/esp-lwip@a45be9e](https://github.com/espressif/esp-lwip/blob/a45be9e438f6cf9c54ec150581819c3b95d5af6b/src/core/dns.c#L921)、
`.pio`にビルド済みlibのみで同梱されソース無し・ESP-IDFの`.gitmodules`経由で
コミットを特定して取得）を確認したところ、該当行は:

```c
pcb_idx = entry->pcb_idx;  // LWIP_DNS_SECURE_RAND_SRC_PORT有効時（既定でON）
err = udp_sendto(dns_pcbs[pcb_idx], p, dst, dst_port);  // dns.c:921
```

`dns_pcbs[]`・`dns_table[]`はどちらも静的配列（.bss）で、coredumpには含まれない
（フラッシュcoredumpはタスクのTCB/スタックのみでヒープ/BSSは対象外）ため、`pcb_idx`が
不正値だったのか`dns_pcbs[]`自体が壊れていたのかはこれ以上追えない。

**代わりに、レジスタダンプそのものが他者の実機と一致する既知issueを見つけた。**
[espressif/arduino-esp32#9388](https://github.com/espressif/arduino-esp32/issues/9388)
（2024-03-20報告）は、全く無関係なハードウェア・スケッチで同じ`udp_sendto`
(`dns_send`→`dns_check_entry`→`dns_tmr`→`dns_timeout_cb`→`sys_check_timeouts`→
`tcpip_thread`という同一コールチェーン)がクラッシュしており、レジスタダンプが
**`A2(=pcb)=0x00000001`・`EXCCAUSE=0x1c`・`EXCVADDR=0x15`・`A5=0x35`(dst_port=53)・
`A6=4`・`A7=0`まで完全一致**していた（スタックアドレスのA1/A3/A4等は当然別ハードウェアなので異なる）。
`pcb`が別ハードウェア・別スケッチで毎回きっちり整数`1`という「本物のポインタでは
まず有り得ない値」に揃うのは、単発の偶発的メモリ破壊ではなく**再現性のある
ロジックバグ**であることを強く示唆する。

Espressifの回答は「ヒープ枯渇で`malloc()`がNULLを返しチェック漏れではないか」という
推測にとどまり確認は取れておらず、`Resolution: Wontfix`・`Type: Question`のまま
2024-04-05にクローズ済み——**upstream(arduino-esp32/esp-lwip)側で根本原因は特定されず、
修正も入っていない。** `lwip.a`はビルド済みプリコンパイル済みライブラリとして配布されて
おり（`dns.c`はこのレポにソースが存在しない）、自前でパッチを当てる経路も無い。

**esp-lwip本体側も当たったが、この件をピンポイントで直したコミットは無かった。**
`dns_pcbs`/`pcb_idx`でissue・commit検索しても無関係な結果のみ——唯一のヒット
（`dns_alloc_pcb`のidx進行バグ修正、2015年）はうちがpinする`a45be9e`(2023-11-27)に
最初から反映済みで無関係。直近のDNS関連コミット(複数IPレコード対応・multi-IP
buffer overflow修正・キャッシュクリアdeadlock対策)は`git compare`で`a45be9e`と
**diverged**——ESP-IDF 4.4.7系列にはそもそも乗っていない別系統の変更と確認した。
現行の既定ブランチ(`2.2.0-esp`)でも該当コード(`dns.c:928,957`)は当時と同じ実装の
ままで、**ESP-IDFを上げても直る保証はない**。`entry->pcb_idx`と`dns_pcbs[]`の
どちらが壊れているかはupstream側でも未解明。

## さらに深掘り: 「値がどこから来るか」の入口が特定できた

3週間で2回という頻度をどう見るか確認するため、`pcb`(=1)という不正値がどの経路で
紛れ込みうるかをさらに追った。

**`dns.c`冒頭のドキュメントコメントに明記されていた**:

> All functions must be called from TCPIP thread.
> @see @ref netconn_common for thread-safe access.

つまりlwIPの生API(`dns_gethostbyname()`等)は**tcpip_threadからしか呼んではいけない**
契約になっている。ところがarduino-esp32の`WiFiGenericClass::hostByName()`
(`WiFiGeneric.cpp:1574`)は、この生APIを**呼び出し元タスクからそのまま直接呼ぶ**:

```cpp
err_t err = dns_gethostbyname(aHostname, &addr, &wifi_dns_found_callback, &aResult);
```

スレッドセーフな`netconn_gethostbyname()`（tcpip_threadへメッセージ経由で処理を
委譲する版）を使わず、生APIを直接呼んでいる——**これ自体がlwIPの契約違反**。

このビルドは`LWIP_TCPIP_CORE_LOCKING`が無効
(`sdkconfig`: `# CONFIG_LWIP_TCPIP_CORE_LOCKING is not set`)なため、アプリ側から
`LOCK_TCPIP_CORE()`で握って回避する手段も無い（ロック自体が意味を持たない設定）。

**さらにタスクの割り当てを確認したところ、両者は同じCPUコア(core0)で衝突しうる
配置だった**（`firmware/src/main.cpp`）:

- `tiT`(tcpip_thread): core0固定・優先度18(`CONFIG_LWIP_TCPIP_TASK_PRIO=18`、
  `CONFIG_TCPIP_TASK_AFFINITY_CPU0=y`)
- `uploaderTask`: core0固定・優先度**1**(`main.cpp:852`、`WiFiClientSecure::connect()`
  →`hostByName()`を呼ぶのはこのタスク)

同じcore0上で、優先度18の`tiT`はいつでも優先度1の`uploaderTask`を横取り(preempt)できる。
`dns_enqueue()`/`dns_gethostbyname_addrtype()`は`dns_table[]`・`dns_pcbs[]`
（どちらも非atomicなグローバル静的配列）を複数ステップで読み書きするため、
**`uploaderTask`がその途中でpreemptされ、`tiT`が`dns_tmr()`で同じ構造体を触ると、
中途半端に書きかけの状態を読んでしまう**——これが`pcb`に整数`1`のような
「本物のポインタでは有り得ない値」が入る具体的な入口だと考えられる。真のSMP競合
（2コア同時書き込み）ではなく、**同一コア上の優先度によるpreemptionレース**。

この機構であれば、無関係な他ハードウェア(arduino-esp32#9388)でも再現する理由に
説明がつく——`hostByName()`とタスク優先度18のtcpip_threadという構成はarduino-esp32を
使う限りほぼ誰でも同じだからだ。発生頻度が低いのは、この競合が起きるには
「DNSキャッシュが切れて`dns_enqueue()`の再割り当て経路(`dns_alloc_pcb()`)まで
実際に踏む」かつ「その数命令の隙間にちょうど`tiT`が割り込む」という2条件が
同時に揃う必要があるため——3週間に2回という頻度は、狙って再現するには稀だが
運用上は無視できない程度、という理解で辻褄が合う。

## 現状の評価

device1は現在`e82f81e`・`reset_reason: PANIC`・`online: true`・heap正常で稼働中——今回の
パニックから正常に再起動できている。**upstream(lwIP/arduino-esp32)側にピンポイントの
fixは無いが、機構自体は「`hostByName()`がlwIPのスレッド契約(tcpip_threadからしか
呼ぶな)を破っている」という具体的な設計上の問題として説明がついた。** `lwip.a`は
プリコンパイル済みで直接パッチは当てられないが、**自前のファーム側での回避策は
理論上ありうる**（今回は調査止まりで実装はしていない）:

- `uploaderTask`の優先度(現在1)を`tiT`(優先度18)以上に上げ、preemptされる窓自体を
  無くす——ただしtcpip_thread側の処理を遅らせる副作用がある変更で、影響範囲の検討が要る
- 自前でDNS解決結果をキャッシュし、`WiFiClientSecure::connect(hostname, ...)`が
  毎回`hostByName()`（＝`dns_enqueue()`の再割り当て経路）を踏む頻度自体を下げる
- 固定IPで接続し、DNS解決そのものを経路から外す（IP変更時の追従は別途必要）

どれも本筋への影響やトレードオフがあるためユーザー判断待ちとし、今回は追加調査を
ここで区切る。発生頻度(3週間で2回・両方自動復旧)を踏まえ、経過観察を継続する。

## 次に何が可能になったか

**全履歴照合が必須ではないと分かった。** coredumpパーティションは次のパニックまで
上書きされないだけで、日常的には「今回の再起動＝このcoredumpの発生源」であることが多い
（前回のような「その機で自動送信機能が入って初めて起動した回」は稀）。
`GET /devices/<id>`の`reset_reason`/`uptime_s`で辻褄を確認できたら、まずラベル自身と
1つ前の公開版の2件だけ照合し、両方不一致だった場合のみ全履歴へ広げる——という優先順位を
[firmware/README.md](../../firmware/README.md#自動送信されたcoredumpの場合-fw_versionラベルを鵜呑みにしない)
に追記した。
