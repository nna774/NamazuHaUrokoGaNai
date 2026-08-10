# batch-uplinkをv2.4.0からv2.8.0へ: デバッグログとOOM安全化を取り込む（2026-08-10）

## 背景

device1の「1本送信成功後、無期限に無応答」調査（別ログ・別PR、TlsMemPool関連）の
過程で、`batch-uplink`本体に4つの変更を積んだ。すべて`batch-uplink`リポジトリ側で
既にマージ・タグ付け済みで、firmware側のpin更新だけが残っていた。

- **v2.5.0**（[PR#14](https://github.com/nna774/batch-uplink/pull/14)）: `pump()`の
  各分岐（WiFi状態・バックオフ・spill読み込みの各段階）にデバッグログを追加。
  「`postBatch begin`が一度も出ないまま止まって見える」現象の切り分けに必要だった。
- **v2.6.0**（[PR#15](https://github.com/nna774/batch-uplink/pull/15)）: **実際のバグ修正。**
  ヒープ枯渇時、`Uploader::loadOldestSpillPath()`内の`File::openNextFile()`が
  `operator new()`失敗→未捕捉例外→`abort()`でクラッシュしていたのをtry/catchで
  安全化。TlsMemPoolの有無に関係なく存在した既存の頑健性バグ。
- **v2.7.0**（[PR#16](https://github.com/nna774/batch-uplink/pull/16)）: `pump()`の
  読み込み失敗ログに`heap_free`/`ESP.getMaxAllocHeap()`を追加。
- **v2.8.0**（[PR#17](https://github.com/nna774/batch-uplink/pull/17)）:
  `heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)`を追加。`ESP.getMaxAllocHeap()`
  (`MALLOC_CAP_INTERNAL`基準)が実際にmalloc()が使える量を過大報告する
  （PR #54で最初に発見）ことの再確認に必要で、実機で`malloc(18032)`失敗の原因が
  本当にこの断片化だったと確定させた。

## 変更

`firmware/platformio.ini`の`lib_deps`と`terraform/build_lambda.sh`の
`UPLINK_VERSION`を`v2.4.0`→`v2.8.0`へ。firmware側のコード変更は無い
(すべて`batch-uplink`側で完結する変更のため)。

## 確認したこと

`pio run -e esp32dev -e adxl355 -e fake-sensor`のビルド成功、
`firmware/test/run.sh`(wireバイト等価テスト)を確認した。
