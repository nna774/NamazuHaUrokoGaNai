# WiFi遮断試験でBatchプール枯渇の飢餓状態を発見・修正した（2026-08-11）

## 経緯

タスク分割版・mutex版を焼いたテスト機で、意図的にインターネットを切って
WiFi瞬断シナリオを試した(`out6.log`/`out7.log`)。すると
`[sampling] newBatch stuck: N consecutive fails`が数千〜1万本超まで際限なく
増え続け、長時間（分オーダー）回復しない現象が出た。

## 原因

`Uploader::enqueue()`側の`ram_`満杯検知(`while (ram_.size() >= maxRam_)`)
だけがspillへの退避トリガーで、これは**新しいバッチが実際に届いた時の副作用**
としてしか発火しない。WiFiが切れると:

1. `ram_`が`kMaxRamBatches`本の未送信バッチで埋まる（送信失敗が続くので空かない）
2. firmware側のBatchバッファプール(`kMaxRamBatches+1`スロット)も使い切る
3. `samplingTask`が`newBatch()`できなくなり詰まる
4. **新しいバッチが作れない→`enqueue()`が二度と呼ばれない→退避のトリガーが
   永遠に来ない飢餓状態**

吸い出しタスク(`batchDrainTask`)自体は健全に動いていた——渡すべき新しい
バッチがsamplingTask側で作れなくなっていた、という切り分けができた
（`enqueue #6`が約5分後に出現し、吸い出し経路自体は生きていたことを確認）。
今回のタスク分割・mutex化とは独立した、単一タスク時代から存在した設計の穴。

## 対策

`batch-uplink`側(`Uploader::pump()`)に「送信の指数バックオフが上限
(`kBackoffMaxMs`=60秒)に張り付いている間は、WiFi接続状態に関わらず
`flushToSpill()`を自発的に呼ぶ」安全弁を追加した([PR #22](https://github.com/nna774/batch-uplink/pull/22)へ追加コミット)。
「毎周期無条件でflush」ではなく「継続して詰まっている時だけ」にしたのは、
平常時にRAMキューをクッションとして使い flash書き込みを避ける、という
既存の設計意図を壊さないため（`kBackoffMaxMs`到達という既存シグナルに
乗っかるだけで、firmware側の変更は不要——Uploaderの中で完結する）。

## 確認したこと

- `test/run.sh`（Batch単体）PASS
- テスト機(fake-sensor)へ書き込み、クラッシュなく起動することを確認

## 確認できていないこと

- バックオフ上限到達を伴う長時間のWiFi遮断シナリオで、実際に飢餓状態が
  解消される（`newBatch stuck`が回復する）ことの実機確認はまだ

## 次に何が可能になったか

`batch-uplink` PR #22にこの修正も含めた状態でレビュー・マージへ進められる。
