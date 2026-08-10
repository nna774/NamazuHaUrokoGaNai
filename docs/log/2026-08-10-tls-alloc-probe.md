# mbedTLSの確保サイズ・同時確保量を実機で計測するプローブを用意した（2026-08-10）

## 背景

`newBatch()`失敗対策の次善策(`docs/design.md`予備案(3)「mbedTLS専用固定
プール化」)に向け、まず実機でTLSの確保サイズ・同時確保量を測る必要が
あった。プールサイズを勘で決めると、小さすぎればプール枯渇でTLSが動かず、
大きすぎれば一般ヒープを圧迫して`newBatch()`側の問題を再現してしまう。

## 実装

`mbedtls_platform_set_calloc_free()`が実際にこのSDK(ESP-IDF側の
`esp_config.h`、vendored`mbedtls/config.h`とは別)で有効になっていることを
確認した上で、calloc/freeを横取りして呼び出し回数・合計/同時確保バイト数・
最大単発サイズを追跡する`firmware/lib/TlsAllocProbe`を追加した。

- 実装は素通しの計測ラッパー(裏では標準calloc/freeを使う)——プールその
  ものではなく、プールサイズを決める実測値を取るためだけのもの。
- 確保のたびに8バイトヘッダを先頭に足してサイズを覚え、free時に差し引く。
- 専用env(`env:tls-alloc-probe`、`env:fake-sensor`を拡張)を追加し、実際の
  ingest/alert TLS送信(batch-uplinkの接続使い回し込み)で測れるようにした。
  本番機のバイナリには含めない(`NAMZ_TLS_ALLOC_PROBE`ビルドフラグでのみ有効)。

## 確認したこと

`pio run -e esp32dev -e adxl355 -e fake-sensor -e tls-alloc-probe`の
ビルド成功、`firmware/test/run.sh`(wireバイト等価テスト)を確認した。

## 次に何が可能になったか

実機でTLSハンドシェイクの実際のフットプリントを測定できる状態になった。
実測結果とmbedTLS専用固定プール(`TlsMemPool`)の実装は別PR。
