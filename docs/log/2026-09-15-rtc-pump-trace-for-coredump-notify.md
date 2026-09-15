# pump()呼び出し前後の状態をRTC memoryへ記録し、coredump通知に「送信詰まり」情報を足す

[2026-09-15-device2-postbatch-tls-handshake-wdt.md](2026-09-15-device2-postbatch-tls-handshake-wdt.md)の
調査で、coredumpのバックトレースは「どの関数で止まっていたか」は分かるが
「いつから・どれくらいの時間止まっていたか」は分からないと判明した——ESP32の
coredumpは各タスクのスタック/TCBのみのスナップショット1枚で、時系列の情報を
持たない。この隙間を埋める目的で実装した。

## 検討過程で分かった制約

当初は「`Uploader::postBatch()`の内部（TCP接続確立/TLSハンドシェイク/ヘッダ
読み取り）の節目でコールバックを呼び、そこでRTC memoryへ記録する」という、より
細かい粒度を狙っていた。しかし`Uploader::postBatch()`は`HTTPClient::POST()`という
1回の巨大なブロッキング呼び出しに丸投げしており、`HTTPClient`自体に
`httpUpdate.onProgress()`のような進捗コールバックが無い(ヘッダ確認済み)ため、
Uploader.cpp(batch-uplink)側からは「接続済み・ハンドシェイク中」の区別が
そもそも見えないと判明した。本当にその粒度が欲しければ`ssl_client.cpp`の
ハンドシェイクループ自体にビルド時パッチ(`firmware/patches/`と同じ手口)を
当てる必要があるが、その領域は過去にDNS関連で3回パッチしてようやく安定した
実績があるだけの未知数の高いコードで、今回の「詰まった時間を知りたい」という
効能に見合わないと判断し見送った。

代わりに、**「`gUploader->pump()`を呼ぶ前後」という粗い粒度**に落とした。
これは`main.cpp`(このリポジトリ)側が完全に制御している呼び出し境界なので、
batch-uplinkには一切手を入れずに実装できる。今回の実例（詰まっていたのは
まさに`pump()`の中）には十分な粒度だった。

## 実装

- `main.cpp`: `RTC_NOINIT_ATTR`な`RtcPumpTrace`構造体(`magic`/`inFlight`/開始時刻
  [`timesync::isSynced()`なら絶対時刻、未同期なら0]/heap空き・最大ブロック/
  WiFi状態/spill件数/RAMキュー件数)を持ち、`uploaderTask`が`pump()`を呼ぶ直前に
  `inFlight=true`+各値を書き、戻ってきたら`inFlight=false`にする。既に同じ値を
  `X-Namz-*`ヘッダとして毎バッチ送っている(`sHeapFreeBuf`等)ので、そのまま
  流用した。
- `setup()`側で、coredump自動送信(`drainToCloud()`)より前にこの構造体を読み、
  `magic`が有効かつ`inFlight==true`なら「前回はpump()の途中で終わった」と判定して
  `X-Namz-Pump-Trace`ヘッダ用の文字列(`k=v;k=v;...`形式)を組む。読んだ時点で
  `inFlight=false`に戻す——LittleFS退避と違い再試行できない値なので、今回の
  送信一発が失敗したら諦めるベストエフォート。
- `CoredumpQueue::drainToCloud()`に`extraHeaderName`/`extraHeaderValue`(既定
  `nullptr`)を追加し、非nullptrの時だけ`/coredump`へのPOSTにそのヘッダを乗せる。
  CoredumpQueue自身は意味づけを持たずただ運ぶだけ(Uploaderの
  `extraRequestHeaderNames`と同じ設計方針)。
- `lambda/ingest/handler.py`の`_handle_coredump()`が`x-namz-pump-trace`ヘッダを
  読み、`_format_pump_trace()`で人間可読な1行(開始時刻をJSTへ変換・heap/wifi/
  backlogをそのまま)に整形して、既存の「コアダンプを回収した」Slack通知本文に
  「送信詰まり」の1行として追記する。ヘッダが無ければ従来通り何も足さない。
  パース失敗時は生値をそのまま出す(壊れた値で通知全体を落とさない)。

## 確認

`pio run -e adxl355`・`-e esp32dev`ともビルド成功、`firmware/test/run.sh`
(影響なし、Batch/NamzWireは未変更)、`pytest lambda/tests`(193件、新規6件含む)
はすべてパス。実機OTA配信・実際に詰まった状態での動作確認はまだ。

## 次に可能になったこと

次に同じ経路(送信タスクのネットワークI/Oで長時間詰まる)でTASK_WDTパニックが
起きた時、Slack通知だけで「いつから詰まっていたか・その時のheap/wifi/backlog
状態」が分かるようになる——USBを挿してcoredumpを吸い出す前段階で、まず送信詰まり
かどうかの一次切り分けができる。

デプロイ(lambda再デプロイ・device1/2への次回OTA)はまだ行っていない。
