# 2号機のkMaxRamBatchesを3→2へ下げた（fix#1/#2だけでは断片化を防げなかった）

## 背景

`docs/log/2026-08-11-fake-sensor-device2-profile-env.md`で用意したテスト機
（実センサ無し、2号機と同じ`kBatchSeconds=15`・`kMaxRamBatches=3`・
バッチ実バイト数18032B）に、PR #72の修正一式(fix #1: Batchプール枯渇
フォールバック撤去、fix #2: `pump()`のRAM優先化)込みのfirmwareを焼いて
様子を見た。

## 3のままだと断片化してDNSが落ちる

`kMaxRamBatches=3`のまま数分動かしたところ、以下を観測した:

- `heap_free`は49000〜50000台と潤沢に見えるのに、`maxblock_8bit`が
  **1396〜1972バイトまで落ち込む**
- `hostByName(): DNS Failed for ...lambda-url...`が繰り返し発生
- `HTTPClient`が`error(-1): connection refused`を繰り返し返す
- `spillCount`が18→23と単調に増え続け、復旧の兆しがない

これは`docs/log/2026-08-11-batch-pool-fallback-heap-corruption.md`で
特定した「ヒープ断片化がDNS解決まで巻き添えにする」症状そのもの。fix #1は
枯渇時の**危険な**mallocフォールバック（ヒープ破壊の直接原因）を消したが、
`kBatchPoolSlots`(=`kMaxRamBatches`+1=4)ぶんの静的プール確保自体は
`kMaxRamBatches=3`のままだと1号機(3スロット)より1本(18KB)多く、断片化への
余裕が元から少ない。fix #1/#2はヒープ破壊は防ぐが、この「そもそも空きが
足りない」問題までは解決しない。

## 2へ下げたら健全になった

`config.h`のADXL355 branchを1号機と同じ`kMaxRamBatches=2`(`kBatchPoolSlots=3`)
に変更し、同じテスト機・同じ条件(古いspillの排出も込み)で再確認した。

| | 3のまま | 2へ変更 |
|---|---|---|
| DNS解決失敗 | 複数回 | **0回** |
| connection refused | 複数回 | **0回** |
| `newBatch stuck` | あり | **0回** |
| `maxblock_8bit` | 1396〜1972 | **23540で安定** |
| POST結果 | ほぼ失敗 | **7/7 成功(code=200)** |
| spillCount | 増え続ける | 23→2→1と順調に排出 |

新規に組んだバッチの`enqueue`間隔もちょうど15008〜15200ms(`kBatchSeconds=15`
通り)で、`len=18032`（2号機実機と同じサイズ、`fake-sensor-device2-profile`
env側のFakeSensor int32化修正が効いている）。

## 決定事項

**`config.h`の`kMaxRamBatches`をADXL355(2号機)側も1号機と同じ`2`へ変更した。**
両ブランチとも値は`2`で揃ったが、由来が別（1号機は2026-08-10のヒープ断片化
実測、2号機は今回のテスト機実測）なのでコメントは分けたまま残し、`#ifdef`は
維持した。

## 次にやること

ユーザーがこのテスト機で意図的なネットワーク切断試験を実施中
（切断中のbacklog蓄積・復旧後の排出・`heap_free`/`maxblock_8bit`推移を見る）。
問題なければ、この`kMaxRamBatches=2`変更とPR #72のfix一式をセットで2号機へ
投入する判断ができる。
