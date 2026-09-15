# 2026-09-06 device1、`udp_sendto`/`pcb=1`クラッシュが再発（既知バグの2件目）

## きっかけ

ユーザーから「device1(fw=e82f81e)起動時にcoredumpが見つかり、S3へ保存された。再起動原因を
調べたい」との依頼。作業機はAWS認証情報未確認・PlatformIO/esp-coredump未セットアップの
新しいマシンだったため、環境構築から行った。

## 対象の特定

`s3://namazu-data-<account-id>/coredump/0001/`には3件あった:

| S3キー | アップロード時刻(JST) | サイズ |
|---|---|---|
| `e82f81e-00001788109835888345.bin` | 2026-08-31 02:10 | 20868B |
| `e82f81e-00001788239108678687.bin` | 2026-09-01 14:05 | 20868B |
| `e82f81e-00001788652472863472.bin` | **2026-09-06 08:54** | **21124B** |

前2件は既存ログ([2026-08-31](2026-08-31-device1-lwip-null-deref-coredump.md)・
[2026-09-01](2026-09-01-device1-udp-sendto-null-deref-coredump.md))で調査済み。
最新の1件が今回の対象。

`GET /devices/0001`で`reset_reason: PANIC`・`boot_epoch_us`を確認したところ
**2026-09-06 08:54:00 JST起動**、coredumpのアップロード時刻(08:54:32、起動33秒後)と
辻褄が合った——[firmware/README.md](../../firmware/README.md#自動送信されたcoredumpの場合-fw_versionラベルを鵜呑みにしない)
の優先順位通り、全履歴照合を経ずラベル自身(`e82f81e`)を信頼して進めた。

## 環境構築（新マシン）

- AWS: `A.R.O.N.A`ユーザーは`sts:AssumeRole`のみの権限（[2026-09-04](2026-09-04-arona-user-namazu-scoped-admin-role.md)
  で決めた構成）。`--profile namazu-admin`が既に設定済みで、それを使うだけでS3アクセスできた
- PlatformIO・`esp-coredump`とも未インストールだったため、`.venv`へ新規インストール
  （`pip install platformio esp-coredump`、PlatformIO 6.2.0 / espcoredump.py 1.17.1）
- `git worktree add --detach <path> e82f81e`でコミットをdetached checkoutし、
  `pio run -e esp32dev`でビルド。toolchain(`toolchain-xtensa-esp32`含む)はPlatformIOが
  自動取得、GDBは`~/.platformio/packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-gdb`
  を流用（手順書通り）

## ビルド検証

再ビルドした`firmware.bin`とS3の`ota/esp32dev/e82f81e.bin`を`cmp -l`でバイト比較したところ、
**1,059,024バイト中65バイトのみ差分**（オフセット177〜208=`app_elf_sha256`欄32バイト＋末尾
チェックサム）——既知のパターンと一致し、コード・rodata等の実体は完全にビット一致と確認できた。
`platformio.ini`の`platform = espressif32`が当時(2026-08-31)まだ未pinのままの版だったが
（pin化は[2026-09-01](2026-09-01-pioarduino-arduino3-poc.md)以降）、今回はたまたま同じ解決先に
なり再現できた。

`esp-coredump`はいつも通りapp_elf_sha256不一致で弾かれた（自前再ビルドである以上原理的に
避けられない）ため、site-packages自体は編集せず実行時モンキーパッチ（`_extract_elf_corefile`の
2箇所の`raise`をログ警告に差し替え）で読み進めた。コアダンプ側が記録する自己参照ハッシュ
(`654194662fad9ff6`)は[2026-09-01]の別クラッシュ時と同じ値——同じ`e82f81e`ビルドが動き
続けていた証拠として整合する。

## クラッシュ内容: 2026-09-01と完全に同一のバグの再発

```
Crashed task: 'tiT' (lwIP tcpip_thread)
exccause: 0x1c (LoadProhibitedCause)
excvaddr: 0x15
pc: udp_sendto (udp.c:540), pcb=0x1
a2(=pcb)=0x1, a5=0x35(dst_port=53), a6=4, a7=0
```

バックトレース: `dns_tmr → dns_timeout_cb → dns_check_entries → dns_check_entry → dns_send
→ udp_sendto`。レジスタ値・コールチェーンとも[2026-09-01の device1調査](2026-09-01-device1-udp-sendto-null-deref-coredump.md)
・[同日の device2調査](2026-09-01-device2-back-to-back-crash-wdt-and-dns-race.md)・
upstream issue[espressif/arduino-esp32#9388](https://github.com/espressif/arduino-esp32/issues/9388)
と**完全一致**。他タスク(`sampling`は次タイマー通知待ち、`batchDrain`はキュー待ち)は健全で、
今回もセンサ・送信パイプライン自体に異常は無い。

根本原因は2026-09-01調査で既に特定済み——`WiFiGenericClass::hostByName()`
(arduino-esp32 `release/v2.x`、EOL済み)がスレッドセーフでない生API`dns_gethostbyname()`を
`uploaderTask`(優先度1・core0)から直接呼び、`tiT`(tcpip_thread、優先度18・同じcore0)による
preemptionで`dns_table[]`/`dns_pcbs[]`(非atomicなグローバル静的配列)の書きかけ状態を読む
競合が起きる。upstream修正([espressif/arduino-esp32#8672](https://github.com/espressif/arduino-esp32/pull/8672))
はarduino-esp32 3.x系列(`NetworkManager`書き直し、`lwip_getaddrinfo()`使用)限定で、
うちが使う2.x系列には反映されていない。今回の調査で新たに判明した事実は無い。

## 発生頻度の更新

このバグ(`udp_sendto`/`pcb=1`)自体は今回で**device1として2件目**(2026-09-01・
2026-09-06、5日間隔)、device2の同型クラッシュ(2026-09-01)を含めると**フリート全体で
3件目**。装置1台に限れば前回確認時の想定より短い間隔での再発——ただし絶対頻度としては
まだ「稀だが無視できない」の範囲内で、緊急対応が必要というほどの急変ではない。

## 現状の評価・次に何が可能になったか

- **新しい原因ではなく、既知の未解決upstreamバグ(arduino-esp32 2.x系列のDNSスレッド安全性
  違反)の再発と確認した。** 2026-09-01時点で洗い出した緩和策候補(`uploaderTask`優先度の
  引き上げ／DNS解決結果の自前キャッシュ／固定IP化／arduino-esp32 3.x移行)はいずれも
  実装されておらず、方針はユーザー判断待ちのまま
- **coredump読み出し手順(firmware/README.md)は新しいマシンでも変更無しでそのまま機能した**
  ——環境構築(PlatformIO/esp-coredump/AWSプロファイル)から再現できることを実地で確認できた
- device1は現在`e82f81e`のまま正常復旧・稼働中(`online: true`)。再発頻度が上がったとみるか
  経過観察を続けるかはユーザー判断
