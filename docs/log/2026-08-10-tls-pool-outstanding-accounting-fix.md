# TlsMemPoolのoutstanding会計ドリフトを修正し、純粋ロジックをホストテスト可能にした

[log/2026-08-10-tls-pool-outstanding-accounting-drift.md](2026-08-10-tls-pool-outstanding-accounting-drift.md)
で特定した原因(`poolCalloc`が加算する生の要求バイト数と、`poolFree`が減算する
ブロックヘッダの実サイズが非対称)に対する修正を実装した。

## やったこと

1. **`firmware/lib/TlsMemPool/TlsMemPoolCore.{h,cpp}`を新設**し、`BlockHeader`・
   `poolAlloc`・`mergeWithNext`・`poolCalloc`・`poolFree`・カウンタ類という
   Arduino/mbedTLS非依存の純粋なポインタ演算部分を丸ごと移した。
   `TlsMemPool.cpp`は`malloc()`でプール用バッファを確保し
   `mbedtls_platform_set_calloc_free()`へ`core::poolCalloc`/`core::poolFree`を
   繋ぐだけの薄いアダプタになった。Serial出力は`WarnFn`コールバック
   (`void(*)(const char*)`)経由にし、コア側は`vsnprintf`でメッセージを組み立てる
   ことでArduino依存を切った。
2. **加算/減算を対称化**: `poolCalloc`は要求バイト数ではなく、確保直後に
   `headerOf(p)->size`で読み返した**ブロックの実サイズ**を`sCurrentOutstanding`に
   加算するよう変更した。`poolFree`は元々ブロックの実サイズを減算していたので、
   これで両者が常に一致し、alignUpによる切り上げや分割スキップ時の余りが
   何であってもドリフトしなくなる。
3. **O(1)の防御チェックを追加**（`poolFree`内）:
   - `b->size`がプール全体を超えていたら、リンクを一切触らずに警告して抜ける
     （壊れたsizeでmergeへ進むと隣接ブロックのヘッダを不正なオフセットで
     書き換えかねないため。実際に破損している証拠は見つかっていないが、
     見つかった時に静かなヒープ破壊へ発展させない安全弁として)。
   - `sCurrentOutstanding`が減算後に0未満へ落ちたら即座に警告する
     （会計対称化で理論上は起こらなくなったはずだが、次に何か想定外が
     起きた時、実機でcall #353147まで気付けなかった前回より大幅に早く
     検知できるようにする保険)。
4. **`checkInvariants()`をコアへ追加**（O(ブロック数)、本番のホットパスからは
   呼ばない診断/テスト専用）: 全ブロック(used+free)のsize合計+ヘッダ分が
   プール全体と一致するか、隣接freeブロックが2つ連続で残っていないか
   (結合漏れ)、physNext/physPrevの相互リンクが一致しているかを検査する。
5. **`firmware/test/test_tls_mem_pool.cpp`を追加**し、`firmware/test/run.sh`に
   組み込んだ(batch-uplinkに依存しないので素のg++でビルドできる)。
   - 基本のalloc/free往復。
   - **分割スキップ境界のケース**（`remain`がちょうど`headerBytes+alignment`の
     閾値で、`poolAlloc`が分割せず元の大きい空きブロックをそのまま返す経路）を
     `blockHeaderBytes()`/`alignment()`アクセサから逆算して意図的に作り、
     修正前のロジックに戻すと一発でこのテストが`outstanding`不一致で落ちる
     ことを確認済み（このテストが今回のバグを実際に検出できる証拠)。
   - TLSの出入りを模した3万回の乱数calloc/free列で、上記3つの不変条件と
     「全部freeし終えたらoutstandingがちょうど0に戻る」を検証。

## 確認したこと

- `firmware/test/run.sh`（batch bytesゴールデン + 新設TlsMemPoolテスト）全緑。
- 加算/減算を対称化する前のロジックに戻した状態で同じテストを走らせると、
  `basic`/`split-skip`/`stress`いずれも`outstanding`不一致で落ちることを確認
  （stressケースは3万回中で-59411まで負ドリフトした）。これがリグレッション
  再発を検出できることの裏付け。
- `pio run -e esp32dev -e fake-sensor -e adxl355` 3env成功。
- `pytest lambda/tests tools/tests` 169件成功。
- 単一タスク前提の崩れ・リンクリスト自体の破損は前回の調査ログの通り見つかって
  いないため、今回は会計対称化と防御チェックの追加にとどめ、リンクリスト
  操作のロジック自体(`poolAlloc`の分割・`mergeWithNext`)は変更していない。

## 実機投入

まだ。次に4294967295番機(fake-sensor)で長時間稼働させ、`sCurrentOutstanding`が
0未満に落ちない(=会計が壊れない)ことと、`checkInvariants`相当の手動確認を
実機ログで確かめること。
