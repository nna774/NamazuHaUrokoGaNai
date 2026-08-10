# テスト機(2号機プロファイル・kMaxRamBatches=2)でネットワーク切断→復帰試験を実施した

## 背景

`docs/log/2026-08-11-device2-ram-batches-reduction.md`で、テスト機
（`fake-sensor-device2-profile`、2号機と同じ`kBatchSeconds=15`・実バイト数
18032B、`kMaxRamBatches`は1号機と同じ`2`へ変更済み）を使い、PR #72の
fix #1/#2込みでも実際にWiFiを切ってbacklogを作った状態でも健全に保てるかを
確認した。ユーザーが手元で意図的にネットワークを切断・再接続する試験を実施。

## 結果（`firmware/out5.log`より）

タイムライン:

- t≈197〜365秒の間に5回、`hostByName(): DNS Failed` → `HTTPClient`
  `connection refused`(POST code=-1)。この間`heap_free`は75000台、
  `newBatch stuck`時の`maxblock_8bit`も20468〜27636を維持
  （`kMaxRamBatches=3`のままだった前回試験で見えた1396〜1972への崩壊は
  発生しなかった）。
- 切断中、複数エピソードで`newBatch stuck`が最大995〜1195連続fail
  （生サンプルの一時欠測）。これは`kMaxRamBatches`の値によらず残る構造的な
  Batchプール枯渇レース（`ram_`上限+`gBatchQueue`待機1本+組み立て中1本で
  理論上1本不足、`docs/log/2026-08-11-batch-pool-fallback-heap-corruption.md`
  参照）によるもので、fix #1のおかげで「安全な欠測」のまま——クラッシュや
  再起動は発生していない。
- t≈413秒でPOSTが`code=200`に復帰、以降16回連続成功。`spillCount`は
  13→…→1と単調に排出され、最終的に`nothing to send, closing idle
  connection`（完全に追いついてidle）まで到達した。

## 結論

`kMaxRamBatches=2`込みの構成で、実際のネットワーク切断→復帰を安全に
乗り切れることを実機で確認した。断片化によるヒープ崩壊・クラッシュは無く、
切断中の一部サンプル欠測は構造的に残るが安全な範囲に収まり、復帰後は
backlogを完全に排出して正常運転へ戻る。

## 次にやること

PR #81（fake-sensor-device2-profileのバッチ実サイズ修正 + `kMaxRamBatches`
2への変更）をレビュー・マージし、2号機への実機投入を検討する段階に進める。
