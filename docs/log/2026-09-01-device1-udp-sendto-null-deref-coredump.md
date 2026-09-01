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

## 現状の評価

device1は現在`e82f81e`・`reset_reason: PANIC`・`online: true`・heap正常で稼働中——今回の
パニックから正常に再起動できている。**これはarduino-esp32同梱lwIPの既知・未解決の
latentバグであり、自前のコードのバグではない。** 発生頻度は3週間で2回・両方とも
自動復旧しており実害は無い。upstreamでwontfix済み・自前でパッチできない以上、これ以上
追っても収穫は薄いと判断し、追加調査は行わない（再発頻度が上がる・実害が出るまでは
経過観察のままとする）。

## 次に何が可能になったか

**全履歴照合が必須ではないと分かった。** coredumpパーティションは次のパニックまで
上書きされないだけで、日常的には「今回の再起動＝このcoredumpの発生源」であることが多い
（前回のような「その機で自動送信機能が入って初めて起動した回」は稀）。
`GET /devices/<id>`の`reset_reason`/`uptime_s`で辻褄を確認できたら、まずラベル自身と
1つ前の公開版の2件だけ照合し、両方不一致だった場合のみ全履歴へ広げる——という優先順位を
[firmware/README.md](../../firmware/README.md#自動送信されたcoredumpの場合-fw_versionラベルを鵜呑みにしない)
に追記した。
