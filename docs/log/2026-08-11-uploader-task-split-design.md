# uploaderTaskを吸い出し/送信の2タスクに割る設計を決めた（2026-08-11）

## 背景

`memo.md`に「batch queueの吸い出しタスク分離」という走り書きがあり、当初は
「RAM/spillの2系統あるうち、吸い出しタスクがspillにどんどん書いていくのは
どうか」という発想だった。整理のため会話で掘り下げた。

## 実際の問題

`memo.md`の発想（RAM経由をやめて常時spillへ直行）が解決しようとしていたのは
「電源断でRAM上のバッチが失われる」問題だが、今回困っていたのは別物——
**WiFiが切れて`uploaderTask`が長時間ブロックすると、その手前の`gBatchQueue`
（深さ4、drop-oldest）が溢れてUploaderに届く前にデータが失われ続ける**問題
だった。これは2026-08-07に device1 で実際に70分間踏んでいる
（[log/2026-08-08-device1-outage-and-deploy-drift.md](2026-08-08-device1-outage-and-deploy-drift.md)、
`docs/design.md`に「2タスクに割る」方向で既に合意済み・未実装と記載あり）。

## 検討して却下した案: firmwareが直接spillファイルを書く

吸い出しタスクが`Uploader`をbypassして直接LittleFSのspillファイルを書く案は
却下した。spillのファイル命名規則(`%020llu.bin`)・`spillCount_`のカウント・
容量上限管理(`evictOldestSpill()`)を firmware 側で二重実装することになり、
2026-08-10に実際に踏んだ「LittleFS整合性チェック違反」
（[log/2026-08-10-littlefs-loop-uploader-race.md](2026-08-10-littlefs-loop-uploader-race.md)）
と同種の壊れ方を再現するリスクがある——**mutexで排他しても、両者が同じ規則で
書いている保証がなければ意味がない**。

**ただし将来的な選択肢としては残す**: `Uploader`側に新しいpublicメソッド
（例えば「RAM未経由で直接spillへ書く」専用API）を足す形なら、spillフォーマットの
単一の真実は`Uploader`の中に残ったまま実現できる。今回はやらないが、
「電源断耐性のためRAMに滞留する時間をさらに削りたい」という要求が具体化したら
検討候補として残しておく。

## flash摩耗の試算

「常時spillへ直行」した場合の書き込み量を試算した。`kBatchSeconds`は
esp32dev機30秒・adxl355機15秒、バッチサイズはどちらも約18KB
（`firmware/src/config.h`）、spillパーティションは全機約11.87MB
（`firmware/partitions_16mb.csv`）。

- esp32dev機: 2,880本/日 × 18KB ≈ 52MB/日
- adxl355機: 5,760本/日 × 18KB ≈ 104MB/日

NORフラッシュの消去回数上限を保守的に10万回とし、LittleFSのウェアレベリングで
パーティション全体に均等分散する前提で単純割りすると、esp32dev機で約63年、
adxl355機で約31年もつ計算になった。LittleFSのメタデータオーバーヘッドで
2〜5倍増しを見込んでも、悪い個体を引いて一桁割り込んでも3〜6年は持つ計算——
**flash摩耗は「常時spill」を却下する理由にはならないと確認した**。

今回は「常時spillへ直行」自体を採用しない（gBatchQueueオーバーフロー問題は
タスク分離だけで解決し、常時spillは別目的＝突然の電源断対策のためだけの話
だと切り分けたため）が、この試算は今後同種の判断（flash書き込み頻度を上げる
変更全般）でも使い回せる目安として残す。

## 採用した設計: 2タスク分割 + Uploader内mutex

`uploaderTask`を「吸い出しタスク」（`gBatchQueue`→`Uploader::enqueue()`のみ、
ブロックしない）と「送信タスク」（WiFi再接続・`pump()`・OTA/再起動判定、既存
ロジックそのまま）に分割する。両方Core0に置き、LittleFS Core0限定ルール
（2026-08-10の修正）は維持する。

`Uploader`内部に`SemaphoreHandle_t mutex_`を追加し、`ram_`・spillディレクトリへの
アクセス（`enqueue()`・`pump()`・`flushToSpill()`・`oldestQueuedStartUs()`・
`ramQueued()`・`spillCount()`・`droppedCount()`）を排他する。**`pump()`内の
ネットワークI/O区間（`postBatch()`呼び出し）は意図的にロックを保持しない**——
ここを握ったままだと、TLSハンドシェイクが詰まった時に吸い出しタスクの
`enqueue()`まで巻き込んで長時間ブロックし、タスクを分けた意味が消える。

`pump()`のRAM分岐は「popしてから送る」方式に変更する。従来の
`ram_.front()`を覗いたまま`postBatch()`する実装だと、送信中に吸い出しタスク側の
`enqueue()`がRAM満杯を検知して同じ先頭要素を`spillOldestRam()`で退避・delete
してしまう競合window（use-after-free相当）が生まれるため、送信対象は先に
`ram_`から取り出して所有権をローカルに移し、失敗時だけ`push_front()`で戻す。

## 次に何が可能になったか

この設計に基づき`batch-uplink`側のmutex実装・firmware側のタスク分割実装に
着手する。実装・ビルド確認・バージョンpinの結果は別ログに書く。
