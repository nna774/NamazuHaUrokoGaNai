# mbedTLS専用固定プールを実装し、実機で謎のハング原因を特定した（2026-08-10）

## 背景

[log/2026-08-10-tls-alloc-probe.md](2026-08-10-tls-alloc-probe.md)で用意した実測プローブ
(`firmware/lib/TlsAllocProbe`、`env:tls-alloc-probe`)を、実機（予備基板、テスト用
device_id=UINT32_MAX、`env:fake-sensor`ベース、spillに142本の未送信バッチを溜めた状態）
で走らせた。

## 実測結果: TLSハンドシェイクの実際のフットプリント

1回目のバックフィル送信(新規ハンドシェイク、`http_.POST()`まで約2.4秒)で:

```
calls=4783 frees=4745 fails=0 outstanding=41825 peak=48304 largest_single=16717 total_requested=325804
```

- 最大単発確保: **16717バイト**。PR #54で見つけた`MALLOC_CAP_8BIT`側の最大空きブロック実測値
  (17396バイト)、`newBatch()`が必要とする18038バイトとほぼ同じ桁——**TLS側の単発ブロックが
  newBatch()と同じ土俵で断片化を奪い合っている**という仮説をそのまま裏付ける数値だった。
- ピーク同時確保: 48304バイト。通算確保回数4783回(mbedTLSは細かい確保を大量に行う)。
- 接続を使い回す設計のため、送信完了後もoutstanding=41825バイトが解放されず残ったまま
  （`spillCount_ > 0`の間は`Uploader::closeIdleConnection()`に到達しないため）。

2回目・3回目の送信は再現性高く全く同じ数値(largest_single=16717など)を示した——測定は
ノイズではなく安定した実測値。

## 実機で「無期限に無応答」バグを再現し、正体を特定した

接続使い回し中の様子を10分間観察したところ、最初の成功送信の直後、mbedTLS呼び出しが
ごく小さく2回動いた(+4回/+4回、確保量の増減なし)のを最後に**完全に無音**になった
（`postBatch begin`の行すら出ない）。パニックも再起動もせず、10分経っても復帰しなかった。
これはdocs/design.mdが2026-08-09に記録した「1本送信成功後、パニックもせず無期限に無応答」
という device1 の実障害パターンと一致する。

原因を特定するため、`batch-uplink`の`Uploader::pump()`自体にタイミングログを追加した
（[batch-uplink#14](https://github.com/nna774/batch-uplink/pull/14)、v2.5.0。postBatch()
自身には既にログがあったが、pump()側の分岐——WiFi状態・バックオフ・spill読み込みの各段階
——には何も無く、「postBatch begin」が一度も出ないまま止まって見える現象を切り分けられ
なかった）。

計装版を焼き直して同じ状況を再現したところ、正体が判明した:

```
pump: spill branch, spillCount=138
pump: loadOldestSpillPath -> /spill/00001786323931438082.bin   (この2ステップ間に約5秒)
pump: opened .../....bin len=18032
pump: read -> -1 (body=0x0)          ← malloc(18032) が失敗している
pump: backoff active (now=... next=...)  ← 以降、指数バックオフ(1s→2s→...→60秒上限)で
                                             同じファイルへの再試行を延々と繰り返す
```

**「無期限に無応答」の正体は、ソケットやTLSハンドシェイクでのブロッキングではなく、
同じ1本の退避ファイルに対する`malloc(18032)`が指数バックオフの上限(60秒)に達しても
永遠に失敗し続けるだけの、単純な——しかし外からは検知不能な——リトライループだった。**
パニックしないのは当然で、コード上は正しく「失敗を検知してバックオフする」という
想定通りの分岐を踏み続けているだけ。ただし出力が一切無いため、運用上は「固まった」
としか見えない。

`malloc(18032)`が失敗する理由は実測プローブの結果とそのままつながる: 使い回し中の
TLS接続が握ったままの約41.8KB(outstanding)が一般ヒープの連続した空き領域を奪っており、
newBatch()と全く同じ理屈で18032バイトの連続ブロックを確保できなくなっていた。

## 対策: mbedTLS専用固定プールを実装した

`firmware/lib/TlsMemPool`を新規実装し、`mbedtls_platform_set_calloc_free()`でmbedTLSの
確保/解放だけを専用の64KiB固定プールへ隔離した（`docs/design.md`の予備案(3)の本実装）。

- プールサイズ64KiB: 実測ピーク48304バイトに約35%の余裕を持たせた値。
- プールは`setup()`冒頭、WiFi/Uploader/OTA初期化より前に`malloc()`で一度だけ確保する
  （static配列にはしない——`dram0_0_seg`のリンク時静的配置制限に当たることは
  [log/2026-08-10-newbatch-buffer-pool-handoff.md](2026-08-10-newbatch-buffer-pool-handoff.md)
  で実証済み）。
- 中身は境界タグ方式のシンプルなfirst-fitアロケータ(隣接空きブロックを即時結合)。
  プールが尽きたらcalloc失敗(nullptr)を返すだけで、mbedTLS自身が想定している
  エラー経路(TLS操作失敗→呼び出し側の既存の指数バックオフ)に安全に委ねられる。
  一般ヒープは一切奪わないため、`newBatch()`側はTLSの都合に一切影響されなくなる。
- `env:tls-alloc-probe`ビルド(計測用、素通しラッパー)とは`main.cpp`のifdefで排他。
  通常ビルド(esp32dev/adxl355、OTA含む)は既定でこのプールが有効になる。

## 確認したこと・まだやっていないこと

- `pio run -e esp32dev -e adxl355 -e tls-alloc-probe`のビルド成功、
  `firmware/test/run.sh`（wireバイト等価テスト）も確認。
- OTA(docs/ota.md、未着手)は`Uploader`とは別のローカル`WiFiClientSecure`を使うが、
  同じグローバルフックの対象になる。OTA先(S3/CloudFront)のTLS footprintは未測定
  ——実装時に別途実機で確認すること。
- device1/device2への投入判断はまだ。

## 実機検証: 狙った効果は確認できたが、新しい壁にぶつかった

`env:fake-sensor`にこのプールを乗せ、詰まらせたままのテスト機（spill 138本、
同じ最古ファイルで`malloc(18032)`が指数バックオフの上限まで失敗し続けていた状態）
へ焼き直して確認した。

**効果はあった。** 起動後最初の試行で、以前は一度も通らなかった`malloc(18032)`が
成功し(`read -> 18032`)、`postBatch begin`→`http_.begin()`→`http_.POST() start`
まで到達した(以前のログでは`read -> -1 (body=0x0)`で毎回止まっていた箇所)。

**しかしその直後、`fopen`の連続失敗→`TASK_WDT`パニック→再起動、を繰り返すように
なった。** 2回目のクラッシュは`addr2line`でバックトレースを解読して原因を特定した:

```
Uploader::loadOldestSpillPath()
  → File::openNextFile()  (spillディレクトリの列挙)
    → std::make_shared<VFSFileImpl>(...) → operator new()
      → 確保失敗 → 例外 → catchされず std::terminate() → abort()
```

**これはTlsMemPool自体のバグ(メモリ破壊)ではない。** アロケータのロジックは
正しく動作しており、実際に`malloc(18032)`を1回通してもいる。原因は、TLS用に
先取りした64KiB固定プールと、`kMaxRamBatches=6`(esp32dev機、最大108KB)の
RAMキューが、spillに詰まったまま(malloc失敗が続く間)同時に一般ヒープを
圧迫し続け、**一般ヒープが本当に底を突いた**こと。底を突いた瞬間、たまたま
`openNextFile()`内部の小さな`new`がそれを踏み、Arduino環境では例外が正しく
処理されずクラッシュに直結する。

副産物として、**TlsMemPoolの有無に関係なく以前から存在した既存の頑健性バグ**
も見つけた——ヒープが極端に逼迫した状態で`loadOldestSpillPath()`のディレクトリ
列挙が走ると、`new`の失敗が例外化されて握りつぶされずabortする。この機体の
ヒープ逼迫のシビアさを踏まえると、TlsMemPoolを入れる・入れないに関わらず
起こり得た潜在バグだったと考えられる。

今回の検証(spill 138本の詰まり＋FakeSensorが休みなく新規バッチを作り続ける
状態)はかなり厳しい人工的ストレスだが、実機のバックフィル時にも近い状況は
起こりうる。検討した選択肢と判断（2026-08-10、ユーザーと相談）:

1. **採用、実施済み。** TLSプールを実測ピーク(48304B)から52KiBまで削り、
   一般ヒープの余裕を増やす。65536→65536-52*1024の差分ぶん一般ヒープが
   広がる。TLS側のcalloc失敗リスクは上がるが、mbedTLSはC実装なので
   TLS操作失敗→既存の指数バックオフという安全な経路に落ちるだけで、
   abortには繋がらない（Aの結論、詳細下記）。
2. **保留(2026-08-10)、作戦としては残す。** `kMaxRamBatches`を減らし
   RAMキューの最大占有量を下げる。`config.h`のコメント通り「溢れたぶんは
   LittleFSへ逃げるのでデータは落ちない」——`kMaxRamBatches`はspillの
   総容量(16MB機で~5.6時間分)とは独立で、減らしても総バッファ容量は
   減らない。副作用は「詰まった時によりflash書き込みが増える(摩耗・
   レイテンシ)」だけで、データロスのリスクは増えない。今回踏んだクラッシュ
   (RAMキュー最大108KB+TLSプールが同時にヒープを圧迫)に直接効くレバーでも
   ある。1(プール縮小)だけで足りるかを見てから、必要なら着手する。
3. **別PRで対応(実施中)。** `loadOldestSpillPath()`側の`new`失敗を先に直す
   (TlsMemPoolと無関係な既存の頑健性バグとして独立に対応する価値がある)。

**実機(device1/device2)への投入判断はまだ。テスト機での検証も継続中。**
