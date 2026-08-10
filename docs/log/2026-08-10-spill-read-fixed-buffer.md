# spill読み込み用mallocの断片化を固定バッファで塞ぎ、Batchプール枯渇の残課題を実機で確認

## 背景

`docs/log/2026-08-10-ota-tls-pool-race.md`のOTA競合調査の続き。internetを断って
テスト機(`device_id=4294967295`、予備基板/`fake-sensor`)にbacklogを大量に溜める
実験をしたところ、`Uploader::pump()`の退避ファイル読み込み(`malloc(len)→read→
POST→free`)が`MALLOC_CAP_8BIT`側の最大連続空きブロック不足で断続的に失敗し
続ける現象を再現した——TLS(`TlsMemPool`)・Batchバッファ([PR #66](https://github.com/nna774/NamazuHaUrokoGaNai/pull/66))は
既に同じ理由で固定プール化済みだったが、この3つ目の`malloc(18032)`だけ
コード内コメントで「未対応のまま残っている」と自覚されつつ手つかずだった。

## 対応: spill読み込み用の固定バッファ

`batch-uplink` v2.10.0([PR #19](https://github.com/nna774/batch-uplink/pull/19))で
`Uploader`にオプトインの`maxSpillReadBytes`を追加。指定すると`begin()`で
一度だけ確保し、以後の退避送信で使い回す(都度malloc/freeをしない)。
firmware側は`kBatchBufferBytes`(=spillファイルの最大サイズ、Batchプールの
スロットサイズと同じ実体)を渡すよう配線した。

## 実機で確認: 直った部分

USB経由で直接書き込み、internet遮断でbacklogが溜まった状態から検証した。

- **spill読み込みの`malloc`は完全に安定した。** 毎回同じアドレス
  (`body=0x3fff2b80`)が返り、`maxblock_8bit`がどれだけ低くても(実測1652まで
  低下した状態でも)`read -> 18032`は一度も失敗しなかった。修正前は
  `maxblock_8bit`が12276〜17396あたりを行き来するだけで`read -> -1`が
  頻発していたのと対照的。
- spillCountはネットワーク側の成否に応じて増減するようになり、
  「メモリ確保で詰まって全く動けない」状態からは脱した。

## 実機で確認: まだ残っている問題

**Batchプール(3スロット、`kMaxRamBatches+1`)が尽きた時の一般`malloc(18032)`
フォールバックは今回手を付けておらず、同じ`MALLOC_CAP_8BIT`断片化の影響を
そのまま受ける。** `samplingTask`に足した診断ログ(`[sampling] newBatch
stuck`、後述)で、`maxblock_8bit`が低い(実測1652まで確認)局面で新しい
バッチの組み立てが数百〜1000回以上連続で失敗する(100Hzなので数秒〜10秒超の
生サンプル欠測)のを直接観測した。一時的に大きな連続領域が空いて自己回復する
こともあったが、今回の観測では前回([docs/log/2026-08-10-ota-tls-pool-race.md](2026-08-10-ota-tls-pool-race.md))
より深く長く詰まる場面もあり、安定して直っているとは言えない。

`POST failed code=-1 (connection refused)`という一見ネットワーク由来に見える
失敗も、`newBatch stuck`の発生タイミングと強く相関しており、実体は
ヒープ断片化で`WiFiClientSecure`/`HTTPClient`内部の確保が落ちている可能性が
高いと見ている(確定はしていない)。

## 診断ログ(一時的、原因特定後に整理すること)

- `[sampling] newBatch stuck: N consecutive fails, heap_free=... maxblock_8bit=...`
  ——`samplingTask`で`newPooledBatch()`が失敗した時、1秒に1回間引いて出す。
- `[sampling] gBatchQueue full, dropping oldest queued batch`——`gBatchQueue`
  (深さ4)満杯時のサイレントdrop経路(`droppedCount()`にも入らない、従来ログ皆無)
  に気付けるようにした。今回の一連の試験では発火を確認していない。

## 実機でのdrop確認

`dropOldestWhenFull_`経路(spill満杯での強制drop)・`gBatchQueue`満杯drop
のどちらも、今回の試験(spillCount最大22本まで観測)では発火しなかった
(該当ログ・"spill full: dropped"を一度も見ていない)。キュー投入済みの
バッチが失われた形跡はゼロ。ただし`newBatch stuck`の間は生サンプルが
そもそもバッチ化されないため、その区間の波形には欠測がある
(Uploaderの「2xxが返るまで捨てない」不変条件の外側の話)。

## 未決事項

- Batchプール枯渇時のフォールバック(`namzwire::newBatch()`の素のmalloc)を
  どう塞ぐかは未着手。プールを増やす(RAM予算と衝突)か、フォールバック自体を
  やめてプール枯渇時は素直に待つ(サンプル欠測は増えるがヒープは汚さない)か、
  設計判断が要る。
- `[sampling] newBatch stuck`/`gBatchQueue full`は診断用。恒久化するか
  撤去するか未定。
- device1/device2への投入判断はまだ。
