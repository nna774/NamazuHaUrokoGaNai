# mbedTLS専用固定プール化に向けた実測プローブを用意する（2026-08-10）

## 背景

PR #54（[log/2026-08-10-newbatch-buffer-pool-handoff.md](2026-08-10-newbatch-buffer-pool-handoff.md)）で
`newBatch()`用の固定バッファプールを試みたが、この機体のDRAM(8bitアクセス可能領域)予算が
既に限界に近く、プールを積むと別の場所(samplingTaskのタスク生成・送信の`pump()`)を
圧迫する構造的な問題にぶつかり、一旦見送った。

次の一手として`docs/design.md`の予備案（信頼性節、案3）に既にあった、
「mbedTLSの確保・解放を`mbedtls_platform_set_calloc_free()`で専用の固定プールに
差し替える」方針を検討する。既存動作（Batch/Uploaderの契約、ワイヤ形式）は
一切変えず、TLSセッションが使うメモリの出どころだけを一般ヒープから隔離する
——この機体で繰り返し問題になってきた「TLSハンドシェイクが大きな連続ブロックを
要求し、`newBatch()`など他の確保と断片化を奪い合う」構図を、TLS側を専用の
固定領域に隔離することで避ける狙い。

## 実装前の下調べ: APIが本当に使えるか確認した

`mbedtls_platform_set_calloc_free()`は`MBEDTLS_PLATFORM_MEMORY`が有効な時だけ
リンクされる。素朴にvendoredの`mbedtls/include/mbedtls/config.h`だけを見ると
無効(`//#define MBEDTLS_PLATFORM_MEMORY`、コメントアウトされたまま)に見えて
一瞬焦ったが、実際にビルドで使われるのはESP-IDFの`mbedtls/port/include/mbedtls/
esp_config.h`で、こちらは`#define MBEDTLS_PLATFORM_MEMORY`が有効（同ファイルの
`CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC`分岐で既定の`esp_mbedtls_mem_calloc/free`に
差し替えられており、これが`heap_caps_calloc(..., MALLOC_CAP_INTERNAL)`相当）。
実際に`mbedtls_platform_set_calloc_free()`を呼ぶビルド(`env:tls-alloc-probe`)が
リンクに成功したことでも確認済み。

## 実装したもの: 計測専用のプローブ（まだプールそのものではない）

プールサイズを当てずっぽうで決めないため、まず実機でmbedTLSが実際に何バイト・
何回・同時にいくつ確保するかを測るプローブを用意した。

- `firmware/lib/TlsAllocProbe/`: `mbedtls_platform_set_calloc_free()`で
  calloc/freeを横取りし、素通しで標準calloc/freeへ委譲しつつ呼び出し回数・
  合計確保バイト数・同時確保量(現在値とピーク)・最大の単発確保サイズを追跡する。
  確保のたびに`size_t`1個ぶんのヘッダを先頭に足してサイズを覚え、freeで
  差し引く方式（マップ等を持たず低オーバーヘッド）。
- `main.cpp`に`NAMZ_TLS_ALLOC_PROBE`ビルドフラグでのみ有効になる呼び出しを
  2箇所追加: `setup()`冒頭（WiFi/Uploaderより前）で`install()`、
  `uploaderTask`ループの`pump()`直後で`printIfChanged()`（差分が無ければ
  何も出さない）。
- `platformio.ini`に`env:tls-alloc-probe`を追加。`env:fake-sensor`
  （2026-08-10のnewBatchプール調査で作った、実センサ無しでWiFi〜Uploaderの
  一気通貫を試せる汎用env）をそのまま拡張しており、既にテスト用device_id
  (UINT32_MAX)がNVSへ焼いてある予備基板でそのまま流用できる。実際のingest/
  alertエンドポイントへの本物のTLS送信（Uploaderの接続使い回し込み）で
  測るため、handshakeだけの人工的なベンチより実態に近い数値が期待できる。

フックはmbedTLSライブラリ全体に対してプロセス単位でしか差し替えられない
（コネクション単位ではない）ため、install()以降に走る全mbedTLS呼び出し
——Uploaderのingest/alert接続だけでなく、将来のOTA(docs/ota.md、未着手)の
TLSも——が対象になる点は`TlsAllocProbe.h`にコメントで残した。「TLS接続は
同時に1本」という design.md の前提が崩れる場面（OTA実装時など）が来たら
再考が要る。

## 確認したこと・まだやっていないこと

- `pio run -e esp32dev -e adxl355 -e tls-alloc-probe`のビルド成功、
  `firmware/test/run.sh`（wireバイト等価テスト）も確認。
- **実機での計測はこれから。** 予備基板を用意してもらい次第、
  `env:tls-alloc-probe`を焼いて`[tls-alloc-probe]`ログを見る。特に見たい数値:
  - 1回のTLSハンドシェイク＋POSTで何バイト確保するか、最大の単発ブロックは
    いくつか（これが専用プールの必要最小サイズの下限になる）
  - 接続使い回し中（2回目以降のPOST）は確保が減るか、それとも毎回ほぼ同じ
    パターンを繰り返すか
  - バックフィル（連続POST）中にoutstandingが単調に増え続けないか
    （増え続けるなら解放漏れ・使い回しの想定と食い違う挙動の兆候）
- プールサイズが決まったら、実際の固定プール実装（バッファプールと同様
  static配列ではなく`setup()`一発`malloc()`方式を踏襲するはず、
  [log/2026-08-10-newbatch-buffer-pool-handoff.md](2026-08-10-newbatch-buffer-pool-handoff.md)
  参照）に進む。
