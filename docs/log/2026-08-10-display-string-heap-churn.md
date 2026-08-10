# loop()の画面更新にあった常時ヒープchurnをString→固定バッファに置き換えた

## 概要

- `newBatch()`失敗対策のバッファプール化見送り（DRAM予算の壁）を受けた
  「無駄遣い調査」の第3弾（第1弾は[Shindoの静的24KBバッファ撤去](2026-08-10-shindo-currentintensity-heap-tmp-buffer-removal.md)、
  第2弾は[LAN内push型OTA撤去](2026-08-10-drop-lan-push-ota.md)）。前2つは
  静的RAM(.data/.bss)の無駄遣いだったが、今回は**動的ヒープの継続的な
  churn（alloc/free反復）**を対象にした
- `firmware/src/main.cpp`の`loop()`が、`status`/`clock`/`ip`の3つの表示用
  文字列を毎回`String`の連結・代入で作っていた。この`loop()`は250ms周期
  （ボタン読み取り分。描画自体は500ms周期）で起動から24/7回り続けるため、
  「1回あたりは数十バイトの小さいalloc」でも積算すると膨大な回数の
  malloc/freeになる。`newBatch()`が要求する18KBの連続ブロックやmbedTLSの
  一時確保と同じヒープを奪い合う相手として、この手の反復allocは断片化を
  招きやすい典型パターン——ただし**これは仮説であり、実測での断片化寄与の
  確認はしていない**
- このプロジェクト自身、頻繁に更新する値（`sUptimeBuf`・`sHeapFreeBuf`・
  `sHeapMaxblockBuf`等）は既に固定char配列+`snprintf`で統一する慣習がある。
  画面更新部分だけがこの流儀から外れていたので、揃えた
- `Display`ライブラリの公開API（`render()`/`renderOtaUpdating()`/
  `renderRebootHold()`）が`const String&`を引数に取っていたため、
  `const char*`へシグネチャ変更した。`lastClass_`（前回描いた震度階級、
  変化検知用のメンバ）も`String`から`char[4]`+`strcmp`に変えた
- `WiFi.localIP().toString()`（これ自体もStringを返しヒープを使う）も、
  `IPAddress`の`operator[]`で4オクテットを直接`snprintf`する形に置き換えて
  経路ごと排除した

## 変更した範囲

- `firmware/lib/Display/Display.h`/`.cpp`: `render`/`renderOtaUpdating`/
  `renderRebootHold`の引数を`const String&`→`const char*`、`lastClass_`を
  `String`→`char[4]`（`strcmp`/`strncpy`で比較・代入）
- `firmware/src/main.cpp`の`loop()`: `String status`→`char status[24]`、
  `String clock`→`char clock[20]`、`String ip`→`char ip[16]`（すべて
  `snprintf`で組み立て）
- `connectWifi()`内のログ出力(`WiFi.localIP().toString().c_str()`、
  接続/再接続時のみ・低頻度)は対象外——ホットパスではないので今回は
  触っていない

## 検証

- `pio run -e esp32dev -e adxl355 -e sensortest -e adxl355-sensortest` 全成功
- `firmware/test/run.sh`（wireバイト等価テスト）確認
- 静的RAM使用量はesp32dev envで82092B→82084B（ほぼ不変、狙い通り——今回の
  目的は静的サイズ削減ではなく実行時のalloc/free回数削減で、`pio run`の
  RAM表示（.data/.bss）には現れない）
- **実機での断片化改善効果そのものは未検証。** ヒープの断片化実測
  （`heap_caps_get_info`等）は今回のスコープ外

## 次に何が可能になったか

`main.cpp`の頻更新値がすべて固定バッファ+snprintfの流儀に揃った。仮説として
挙げていた「Stringの反復allocが断片化に寄与している」という疑いのうち、
少なくとも常時稼働のloop()側は塞いだ。まだ検証していないのは、
(1) 実際にこの変更で`newBatch()`失敗の再現頻度が下がるか（実機で長時間
運用してみないと分からない）、(2) `config.h`のコメントで以前から疑われている
mbedTLSの一時確保側——プロールを使ったバッファ確保の断片化寄与。
どちらも実機投入して初めて確かめられる。
