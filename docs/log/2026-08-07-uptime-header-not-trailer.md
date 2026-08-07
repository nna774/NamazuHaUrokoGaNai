# 稼働時間の運び方を、wireトレイラーからHTTPリクエストヘッダに作り直した

[前ログ](2026-08-07-uptime-strategy.md)で「wire v2トレイラーに新種別を足す」設計に
していたのを、同日中に撤回した。実装はまだ始めていないので、コード変更は無く
`docs/uptime.md`の書き直しだけ。

## 何を決めたか

稼働時間(`esp_timer_get_time()`の生値)は、wireトレイラーではなく**HTTPリクエスト
ヘッダ**（`X-Namz-Uptime-Us`、`fw_version`の`X-Namz-Fw-Version`と同じ経路）で送る
ことにした。batch-uplinkの`Uploader::extraRequestHeaderNames/Values`（v1.6.0）は
「呼び出し側がvalues配列の指す先を毎回書き換えてよい」設計だとソース
（`batch-uplink/src/Uploader.h`のコメント）で確認できたので、**batch-uplinkの変更・
バージョンpinの変更ともに不要**。wire v2トレイラー案より軽い。

あわせて、今回の判断を一般化した使い分けの原則を`docs/uptime.md` §2.3に書いた:

- センサが測った値（測定データの一部）→ wireトレイラー（温度がこれ）
- プロセス・デバイスの状態（測定とは別の「今の情況」）→ HTTPリクエストヘッダ
  （`fw_version`・稼働時間がこれ）

## なぜ覆したか

ユーザーから「トレイラーに入れるとデータには要らないのに保存されちゃわないか」と
指摘された。その通りで、トレイラーはバッチ本体の一部として`ingest`が無加工で
`raw/`にS3保存する（`_handle_batch`）。稼働時間は「今このバッチを送った瞬間の1値」
だけ要る値で、保存済みのraw/バッチを後から読み返して過去の稼働時間を知りたい場面が
無い——サーバ(ingest)がその場で読んで`boot_epoch_us`の逆算に使い、`namazu-devices`に
最新値だけ残せば十分。`raw_retention_days`（既定90日）ぶん無意味に保存され続けるのは
筋が悪い。

指摘を受けて`fw_version`の運び方を確認したら、既に同じ問題を避けた前例
（HTTPヘッダ、wireペイロードに乗せない）が存在すると分かった。しかも
`extraRequestHeaderNames/Values`のAPI自体が「毎回値を書き換えてよい」前提で
設計されていた（`watchResponseHeaders`と対称の汎用API、[remote_restart.md](../remote_restart.md)の
`X-Namz-Restart`もこの仲間）。稼働時間は`fw_version`と同じ「プロセスの状態」であって
「センサの測定値」ではないので、同じ経路に乗せるのが素直だった。

## 何が覆ったか

[前ログ](2026-08-07-uptime-strategy.md)の「wire v2トレイラーに`kTrailerUptimeUs = 2`を
足す」設計は撤回。`firmware/lib/NamzWire/WireFormat.h`・`lambda/common/wire.py`への
変更は不要になった（実装はまだ始めていないので、撤回によるコード上の後始末は無い）。

`millis()`の折り返しバグ（§5）・サーバ側の再起動検知ロジック（`boot_epoch_us`の逆算・
`device_meta.py`への追記）は変更なし。運び方（トレイラーかヘッダか）だけが変わった。

## 何が可能になったか

- batch-uplinkに一切触れずに実装できるようになった（バージョンpinの変更も不要）。
- 「センサ値はトレイラー・プロセス状態はヘッダ」という原則ができたので、次に似た
  種類のデータ（例えば将来のRSSI・空きヒープ量のような診断値）を足す時に、
  トレイラーかヘッダかで迷わず判断できる。
