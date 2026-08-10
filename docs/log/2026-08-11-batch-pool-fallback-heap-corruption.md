# Batchプール枯渇時の素朴mallocフォールバックがヒープを壊しDNSまで巻き添えにしていた件を実機ログで特定した

## 背景

device1の実機で「spillが溜まってる間、DNS解決自体が`hostByName(): DNS Failed`で
繰り返し失敗する」という報告があった。`heap_free`は50KB前後で潤沢に見えるのに
何度も落ちる——ユーザーの直感（メモリ不足では？）を手がかりに調査した。

これまでの調査（`docs/log/2026-08-10-spill-read-fixed-buffer.md`の「まだ残って
いる問題」）で、`namzwire::newBatch()`の素のフォールバックmallocだけが
`MALLOC_CAP_8BIT`断片化対策(TlsMemPool・Batchバッファプール・spill読み込み
固定バッファ)の外に残っている、と自覚はされていたが未確認のままだった。

## 実機ログでの特定

原因不明のヒープ変動をその場で切り分けるため、一時的な計装を実機に焼いて
確認した（この計装自体はコミットしない、`.claude/worktrees/tingly-dazzling-fox`
で使い捨て）:

- `firmware/lib/batch-uplink/`にbatch-uplink v2.10.0をローカルでvendorし、
  `pump()`の既存ログ(`spill branch`・`loadOldestSpillPath ->`・`opened`・
  `postBatch begin`)に`heap_free`/`maxblock_8bit`を追加。`platformio.ini`の
  `lib_deps`を一時的にコメントアウトしてこちらを使わせた。
- `firmware/src/main.cpp`に`logHeapIfChanged(tag)`を追加（値が変化した時だけ
  出す）。`uploaderTask`ループの要所・`loop()`(Core1)・`WiFi.onEvent`全般に
  仕込んだ。

実機ログ(spillファイル140本超のbacklog状態)を見ると、ヒープの段差は
`loop()`(Core1)の1tick(250ms)の間に丸ごと起きており、`pump()`側のどのログとも
噛み合っていなかった。次にプール枯渇のフォールバック(`main.cpp`の
`newPooledBatch()`)自体にもログを足して確認したところ、段差の直前に
必ず出ることを直接確認した:

```
[heap-diag] batch-pool-exhausted, falling back to raw malloc(18064) heap_free=73580 maxblock_8bit=25588 t=109163765
[heap-diag] loop(Core1)              heap_free=55436 maxblock_8bit=7924 t=109294196   ← 直後に丸ごと落ちる
```

## 根本原因

1. `kMaxRamBatches=2`(int16機)に対しBatchプールは`kMaxRamBatches+1=3`スロット
   （「RAMキュー2本+組み立て中1本」の見積もり）。
2. `pump()`はspillファイルを常にRAMキューより優先して送る。spillに140本超
   溜まっている間、spillCountが0になることは事実上なく、**RAMキューに積まれた
   バッチは一本も送信されない**。ただし`Uploader::enqueue()`は`ram_`が上限に
   達したら`spillOldestRam()`で最古をLittleFSへ退避するため、`ram_`自体は
   常に2本ちょうどに張り付く。
3. 一方`samplingTask`はバッチを組み終えると即座に`gBatchQueue`へpushし、間を
   置かず次の`newPooledBatch()`を呼ぶ。`gBatchQueue`から`Uploader::enqueue()`
   への吸い出しは`uploaderTask`ループ先頭でしか起きないため、「`ram_`が上限の
   2本+`gBatchQueue`で吸い出し待ちの1本+組み立て中の1本」で瞬間的に4本必要に
   なる場面がある。プールは3本しかないため、ここで確実に枯渇する。
4. 枯渇時のフォールバックは`namzwire::newBatch()`の素の`malloc(18064)`。この
   機体は`MALLOC_CAP_8BIT`側の最大連続ブロックが**17396バイトで頭打ち**
   （PR #54で最初に実測した値と完全一致、この機体固有の局所最適）。
   18064 > 17396なので、**このフォールバックはほぼ確実に失敗し続ける**。
5. 失敗するたびに`samplingTask`は既存の「メモリ不足なら次サンプルで再挑戦」
   経路(`cur->valid()==false`)に落ちるが、10ms(100Hz)ごとに同じ`malloc(18064)`
   を再挑戦するため、**無駄な失敗malloc呼び出しを延々繰り返しながら生サンプルを
   捨てる**。実機ログでは`batch-pool-exhausted`が2989回、`[sampling] newBatch
   stuck`が39エピソード（最長1531連続fail ≈ 15秒ぶんの欠測）観測された。
   パニック再起動はしていない（`[boot]`は起動時の1回のみ）。

**このフォールバックがまれに成功した場合**（一時的に断片化が緩んで
`maxblock_8bit`が18064を超えた瞬間）は、確保した約18KBが次のPOST試行と
同時に走り、TLS/DNS解決側が必要とする連続ブロックを奪う——これが最初に
観測した「spillが溜まってるとDNSがこける」の直接原因。

## 決定した対応（実装・実機確認済み）

1. **`newPooledBatch()`のフォールバックを削除し、プール枯渇時は`nullptr`を
   返して`samplingTask`の既存の「次サンプルで再挑戦」経路に直接乗せた。**
   これは新しくデータを捨てる仕組みを足すのではない——上記の通り、元の
   コードも同じ結果（生サンプル欠測）に、失敗確定のmalloc呼び出しを10msごとに
   繰り返すという無駄な経路で到達していた。フォールバックを消せば同じ欠測が
   ヒープを汚さず・CPUも無駄食いせず起きるだけになる。`firmware/src/main.cpp`
   だけで閉じる変更。
2. **`Uploader::pump()`の送信優先順位を「spill優先」から「RAMキュー優先」へ
   変更した。** `ram_`が慢性的に上限で張り付く状態（今回の枯渇の根本原因）を
   解消する狙い。代償として、大量backlog復旧中はspillの吐き出しが新規バッチに
   割り込まれやすくなり遅くなる（どちらのデータをどれだけ待たせるかの
   トレードオフ、データを失う話ではないため判断は軽い）。`batch-uplink`
   （外部リポジトリ、Electabuzzと共有）側の変更のため、v2.11.0として
   別途タグ付け・push・`platformio.ini`のpin更新を行った。

## 実機確認

device1で同一条件（spill 140本超のbacklog）で修正前後を比較した。

| | 修正前(out2.log、2.5分) | 修正後(out3.log、4分超) |
|---|---|---|
| `batch-pool-exhausted` | 2989回 | **0回** |
| `[sampling] newBatch stuck` | 39エピソード（最長15秒） | **0回** |
| DNS解決失敗 | 複数 | **0回** |
| POST失敗(`code=-1`/`code=-3`) | 複数 | **0回**（19/19成功） |
| `heap_free`/`maxblock_8bit` | 55000台/1780まで劣化 | **75740前後/27636で完全に横ばい** |

修正後もspillの排出（`spillCount`）は155→140まで単調に減っており、RAM優先化の
代償として懸念した「spill復旧が止まる」という実害はこの観測窓では出ていない
（新しいバッチは約30秒に1本の頻度で、送信自体は数百ms程度で終わるため、
spillの排出をほとんど阻害しない）。

`pio run -e esp32dev -e adxl355 -e fake-sensor`・`firmware/test/run.sh`・
batch-uplink側の`test/run.sh`（Batch単体テスト）確認済み。

コミット: `98be62c`（フォールバック撤去）・`724ea1b`（v2.11.0へのpin更新）。
batch-uplink側は`nna774/batch-uplink`の`ram-priority-over-spill`ブランチ・
`v2.11.0`タグ。
