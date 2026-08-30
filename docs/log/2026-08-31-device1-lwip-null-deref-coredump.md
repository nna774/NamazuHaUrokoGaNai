# device1、初のcoredump自動送信——lwIP内のNULL参照クラッシュ、device2のWDT件とは無関係

同じタイミングでSlack通知が2件届いた:

- `coredump/0002/a96e956-00001788108264719166.bin`（device2）——
  [2026-08-31-device2-ota-pull-wdt-panic.md](2026-08-31-device2-ota-pull-wdt-panic.md)で
  既に調査済みの**同一ファイル**（S3キーが完全一致）。新情報ではない。
- `coredump/0001/e82f81e-00001788109835888345.bin`（device1）——**device1で初めて
  自動回収されたcoredump**。中身を確認したところ、device2のOTA/WDT問題とは
  無関係の、別種のクラッシュだった。

## シンボライズ

手順は前回と同じ（[firmware/README.md](../../firmware/README.md#クラッシュ後のcoredump吸い出し)）。
device1は`env:esp32dev`（IIS3DHHC機）。`e82f81e`コミットで再ビルドし、
`s3://namazu-dashboard-486414336274/ota/esp32dev/e82f81e.bin`と`cmp -l`で照合——
差分は64バイトのみ（`app_elf_sha256`フィールド32バイト＋末尾チェックサム32バイト、
過去と同型のパターン）でコード実体の一致を確認した。

## 結果: WDTではなく本物のメモリフォールト

```
Crashed task: 'tiT' (lwIPのTCP/IP内部タスク)
exccause: 0x1c (LoadProhibitedCause)   ← WDTのabort()由来ではない、実際の不正読み取り例外
excvaddr: 0x15                          ← ほぼNULLに近いアドレス
pc: tcp_listen_input (tcp_in.c:681、tcp_inputへインライン化)
```

device2のcoredump（`task_wdt_isr`→`abort()`の自己パニック）とは全く違う種類——
今回は例外ハンドラが「実際に無効なアドレスへの読み取り」を捕捉したものであり、
lwIPのTCP受信処理内でNULLに近いポインタを参照して落ちている。

**frame 1以降は信用しない。** GDBの巻き戻しは`tcp_listen_input`→`alloc_socket`→
`free_socket_locked`→...と続くが、`tcp_listen_input`が`alloc_socket`を直接呼ぶ経路は
無く、`tcp_input(p=0x1)`のような明らかにおかしい引数値も出ている——最適化ビルドで
下位フレームのDWARF位置情報が壊れている。信頼できるのは例外レジスタ
(exccause/excvaddr)と、フレーム0のシンボル位置（`tcp_listen_input`, tcp_in.c:681）
までに留める。

## 未確定: いつのクラッシュか

**device1にとって今回が初めてのcoredump自動アップロードのため、`e82f81e`という
fw_versionラベルは実際のクラッシュ時期を保証しない**——
[2026-08-30の初回device2 capture](2026-08-30-coredump-device2-first-real-capture.md)と
同じ制約。coredumpパーティションは単一image・次のパニックまで上書きされない仕様
なので、今回拾えたのはdevice1がこれまでに経験した最後のクラッシュでしかなく、
それが`e82f81e`稼働中に起きた保証はない（`e82f81e`自体はOTA配布物のバケット名を
固定値化しただけの無関係な変更で、直接の疑いは薄い）。

## 現状の評価

device1は現在`fw_version: e82f81e`・`reset_reason: SW`・heap正常で稼働中。
実害が継続している様子はない。lwIP内部のNULL参照は自前のアプリコードのバグでは
なく、フレームワーク(esp32-arduino-lib-builder同梱lwIP)側の潜在バグの可能性がある
——再発頻度・トリガ条件とも不明なため、**現時点では経過観察とし、追加調査
（発生条件の特定、esp-idf/lwIPの既知issue照合等）は着手していない**。
