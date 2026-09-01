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
偶然の一致か、lwIPのPCB管理に潜む共通のバグかは未調査。

## 現状の評価

device1は現在`e82f81e`・`reset_reason: PANIC`・`online: true`・heap正常で稼働中——今回の
パニックから正常に再起動できている。前回同様、実害が継続している様子はなく、根本原因
（lwIPのDNS再送処理でpcbが破壊される経路）の追加調査は未着手。

## 次に何が可能になったか

**全履歴照合が必須ではないと分かった。** coredumpパーティションは次のパニックまで
上書きされないだけで、日常的には「今回の再起動＝このcoredumpの発生源」であることが多い
（前回のような「その機で自動送信機能が入って初めて起動した回」は稀）。
`GET /devices/<id>`の`reset_reason`/`uptime_s`で辻褄を確認できたら、まずラベル自身と
1つ前の公開版の2件だけ照合し、両方不一致だった場合のみ全履歴へ広げる——という優先順位を
[firmware/README.md](../../firmware/README.md#自動送信されたcoredumpの場合-fw_versionラベルを鵜呑みにしない)
に追記した。
