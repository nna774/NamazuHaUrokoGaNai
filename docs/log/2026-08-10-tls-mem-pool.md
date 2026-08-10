# mbedTLS専用固定プールを実装し、実機で「無期限に無応答」の正体を特定した（2026-08-10）

## 背景

`namzwire::newBatch()`(=`Batch`のmalloc())が、ヒープに十分な空きがあるように
見えても失敗する現象を実機で繰り返し踏んでいた(PR #54)。この調査を引き継ぎ、
`docs/design.md`の予備案(3)「mbedTLS専用固定プール化」の実装に着手した。

## 実測: TLSハンドシェイクの実際のフットプリント

実測プローブ(`firmware/lib/TlsAllocProbe`、別PR、`env:tls-alloc-probe`)を実機
（予備基板、spillに142本の未送信バッチを溜めた状態）で走らせたところ:

```
calls=4783 frees=4745 fails=0 outstanding=41825 peak=48304 largest_single=16717 total_requested=325804
```

- 最大単発確保: 16717バイト。PR #54で見つけた`MALLOC_CAP_8BIT`側の最大空き
  ブロック実測値(17396バイト)、`newBatch()`が必要とする18038バイトとほぼ同じ
  桁——TLS側の単発ブロックが`newBatch()`と同じ土俵で断片化を奪い合っている
  という仮説をそのまま裏付ける数値。
- ピーク同時確保: 48304バイト。
- 接続を使い回す設計のため、送信完了後もoutstanding=41825バイトが解放されず
  残ったまま（`spillCount_ > 0`の間は`Uploader::closeIdleConnection()`に
  到達しないため）。

## 実機で「無期限に無応答」バグを再現し、正体を特定した

接続使い回し中の様子を10分間観察したところ、最初の成功送信の直後、mbedTLS
呼び出しがごく小さく2回動いた(+4回/+4回、確保量の増減なし)のを最後に完全に
無音になった（`postBatch begin`の行すら出ない）。パニックも再起動もせず、
10分経っても復帰しなかった。

原因を特定するため、`batch-uplink`の`Uploader::pump()`自体にタイミングログを
追加([batch-uplink#14](https://github.com/nna774/batch-uplink/pull/14)、
v2.5.0)して計装版を焼き直したところ、正体が判明した:

```
pump: spill branch, spillCount=138
pump: loadOldestSpillPath -> /spill/00001786323931438082.bin   (この2ステップ間に約5秒)
pump: opened .../....bin len=18032
pump: read -> -1 (body=0x0)          ← malloc(18032) が失敗している
pump: backoff active (...)  ← 以降、指数バックオフ(1s→2s→...→60秒上限)で
                                同じファイルへの再試行を延々と繰り返す
```

**「無期限に無応答」の正体は、ソケットやTLSハンドシェイクでのブロッキングでは
なく、同じ1本の退避ファイルに対する`malloc(18032)`が指数バックオフの上限
(60秒)に達しても永遠に失敗し続けるだけの、単純な——しかし外からは検知不能な
——リトライループだった。** パニックしないのは当然で、コード上は正しく
「失敗を検知してバックオフする」という想定通りの分岐を踏み続けているだけ。

`malloc(18032)`が失敗する理由は実測プローブの結果とそのままつながる:
使い回し中のTLS接続が握ったままの約41.8KB(outstanding)が一般ヒープの連続
した空き領域を奪っており、`newBatch()`と全く同じ理屈で18032バイトの連続
ブロックを確保できなくなっていた。

## 対策: mbedTLS専用固定プールを実装した

`firmware/lib/TlsMemPool`を新規実装し、`mbedtls_platform_set_calloc_free()`
でmbedTLSの確保/解放だけを専用の52KiB固定プールへ隔離した。

- プール自体は境界タグ方式のシンプルなfirst-fitアロケータ(隣接空きブロックを
  即時結合)。プールが尽きたらcalloc失敗(nullptr)を返すだけで、mbedTLS自身が
  想定しているエラー経路(TLS操作失敗→呼び出し側の既存の指数バックオフ)に
  安全に委ねられる。一般ヒープは一切奪わないため、`newBatch()`側はTLSの
  都合に一切影響されなくなる。
- プールは`setup()`冒頭、WiFi/Uploader/OTA初期化より前に`malloc()`で一度
  だけ確保する（static配列にはしない——`dram0_0_seg`のリンク時静的配置
  制限に当たることはPR #54で実証済み）。
- サイズは52KiB: 実測ピーク48304バイトへ約8%の余裕。64KiBで最初に実装した
  ところ、一般ヒープ(RAMキュー最大108KB+この確保分)を同時に圧迫しすぎ、
  ヒープ枯渇によるabortを実機で誘発したため縮小した（詳細は別PR「LittleFS
  競合修正」・batch-uplink v2.6.0のtry/catch安全化を参照）。

## 確認したこと

- `pio run -e esp32dev -e adxl355 -e fake-sensor`のビルド成功、
  `firmware/test/run.sh`（wireバイト等価テスト）確認。
- 実機検証: 詰まらせたテスト機(spill 138本、同じ最古ファイルで
  `malloc(18032)`が指数バックオフの上限まで失敗し続けていた状態)へ焼き
  直したところ、起動後最初の試行で以前は一度も通らなかった`malloc(18032)`
  が成功し(`read -> 18032`)、`postBatch begin`→`http_.begin()`→
  `http_.POST() start`まで到達した。狙った効果を確認済み。

## まだやっていないこと

- OTA(docs/ota.md、未着手)は`Uploader`とは別のローカル`WiFiClientSecure`を
  使うが、同じグローバルフックの対象になる。OTA先(S3/CloudFront)のTLS
  footprintは未測定——実装時に別途実機で確認すること。
- device1/device2への投入判断はまだ。
