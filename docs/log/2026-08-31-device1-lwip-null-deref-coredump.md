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

## いつのクラッシュか特定できた: `5dab9a4`(2026-08-11公開)、20日前

coredump自体にRTC/壁時計のタイムスタンプは無い（ESP-IDFのフォーマットはTCB/スタック+
バージョン+チェックサムのみ）。ただし`esp_app_desc_t.app_elf_sha256`(ビルドごとに
変わる自己参照ハッシュ)をcoredumpから読み取り、`publish_ota.sh`が削除も再ビルドも
しないため丸ごと残っているS3上の全履歴`.bin`（`ota/esp32dev/*.bin`、17版）と
1件ずつバイト照合したところ、**`5dab9a4`(2026-08-11 08:30公開、PR #79
「uploaderTaskを吸い出し/送信の2タスクに分割する」)と完全一致**した。

つまり`e82f81e`(S3キー・アップロード時点のラベル、2026-08-31公開)ではなく、
**20日前の`5dab9a4`稼働中に発生したクラッシュ**——device1がこの間何度再起動しても
（coredump自動送信機能が無かったので）気づかれずコアダンプパーティションに
居座り続け、今回初めて自動送信機能を持つ版が起動したことで掘り起こされた。
手順は[firmware/README.md](../../firmware/README.md#自動送信されたcoredumpの場合-fw_versionラベルを鵜呑みにしない)に
一般化して追記した。

## 現状の評価

device1は現在`fw_version: e82f81e`・`reset_reason: SW`・heap正常で稼働中。
実害が継続している様子はない。lwIP内部のNULL参照は自前のアプリコードのバグでは
なく、フレームワーク(esp32-arduino-lib-builder同梱lwIP)側の潜在バグの可能性がある
——`5dab9a4`から現在の`e82f81e`まで17回のOTA更新を経ても再発報告が無い(今回まで
気づけていなかっただけの可能性も残るが)ため、**現時点では経過観察とし、追加調査
（発生条件の特定、esp-idf/lwIPの既知issue照合等）は着手していない**。
