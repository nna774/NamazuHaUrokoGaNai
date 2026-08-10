# 壊れた退避ファイルがキューを永久に詰まらせる問題への対処

## 何が起きたか

実機のログに以下が繰り返し出ていた。

```
[uplink-debug] pump: opened /spill/00001786378889865868.bin len=0
[uplink-debug] pump: read -> 0 (body=0x3fff1a84) ...
[uplink-debug] http_.POST() -> code=400
[uploader] POST failed code=400 (...)
[uplink-debug] pump: postBatch(spill) -> 0
```

電源断等のタイミングでLittleFSに0バイト（または途中で切れた）退避ファイルが
できていた。`Uploader::pump()`はspillファイルを常に「最古から」選ぶが、この
ファイルはボディが空/壊れているのでingestの`wire.parse()`が例外を投げて
必ずHTTP 400を返す。`pump()`は送信成功(2xx)時にしか`removeSpill()`しない
ため、同じ壊れたファイルを毎回選んでは400で失敗しバックオフして戻る、を
永遠に繰り返し、それより新しい退避データが一切先に進めなくなっていた
（`spillCount_`が減らない）。

ただしRAMキューは別枠で優先送信される（2026-08-11の変更、
[log/2026-08-11-batch-pool-fallback-heap-corruption.md](2026-08-11-batch-pool-fallback-heap-corruption.md)
参照）ため、この間もライブの新規データ送信自体は生きていた。OTAトリガーは
バッチ送信成功へ便乗する方式なので、この状態でもOTA配布で復旧できると判断した。

## 対処

`batch-uplink`に`discardSpillOn400`オプション(既定false)を追加した
（[PR #21](https://github.com/nna774/batch-uplink/pull/21)、`v2.12.0`）。
`true`の時だけ、退避ファイルのPOSTが**HTTP応答コードちょうど400**（サーバが
実際に応答してボディを拒否した場合のみ。403やタイムアウト・接続失敗など
コードを伴わない失敗は対象外）で拒否されたら、そのファイルは二度と成功
しないとみなして即座に`removeSpill()`する。

`Uploader`はワイヤ形式を知らない設計（CLAUDE.mdの不変条件）なので、0バイトと
「途中で切れた半端なbin」を別々にローカル検知するのではなく、**ingestの
wire.parse検証結果(HTTP 400)を一つのシグナルとして使う**ことでどちらも
一律に拾えるようにした。これは`Uploader.h`冒頭の不変条件「2xxが返るまで
バッチを捨てない」への2つ目の明示的な例外（1つ目は既存の`dropOldestWhenFull`）。
既定はfalseなので、この変更単体ではElectabuzz等の既存呼び出し側の挙動は
変わらない。

`firmware/src/main.cpp`で`discardSpillOn400=true`を渡してオプトインし、
`firmware/platformio.ini`・`terraform/build_lambda.sh`のpinを`v2.12.0`へ揃えた。

## 確認したこと・していないこと

- batch-uplinkの既存ホストテスト(`test/run.sh`、Batchのみ対象)はPASS
- `pio run -e esp32dev -e adxl355`がタグ`v2.12.0`を実際に取得してリンクまで成功
- 実機での0バイトspill自動削除の動作確認はまだ（次はOTAでテスト機
  (device 4294967295)へ配布して確認する予定）
