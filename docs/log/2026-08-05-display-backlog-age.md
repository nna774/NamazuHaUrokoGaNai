# TFT表示に未送信キューの遅延時間を出す

「何件溜まってるか」だけでなく「どれくらい遅れてるか」も画面で見たい、という
要望から。既存の画面右下(backlog>0の時だけ`buf:N`を出す枠)に経過時間を足す形にした。

## 何を決めたか

- 画面右下の枠を`buf:12 18m`のように「件数 + 経過分(または秒)」に拡張する。
  新しい表示領域は増やさない。IPは元々backlog=0(正常)の時しか出ないので、
  そこはそのまま。
- 件数(`backlog`)は`spillCount()`だけでなく`spillCount()+ramQueued()`の合計に直した。
  従来はLittleFS退避分しか数えておらず、退避が要らない程度の少量バックログ
  (RAMキューに乗ったまま)は画面上0件のように見えていた。
- 遅延の秒数を得るため、batch-uplinkに`Uploader::oldestQueuedStartUs()`を
  追加した（別PR、[batch-uplink#2](https://github.com/nna774/batch-uplink/pull/2)）。
  送信順序（退避ファイル優先→RAMキュー先頭）と同じ基準で最古のバッチの開始時刻を返す。
  経過時間への変換（`timesync::nowUs()`との差）はプロジェクト側(`main.cpp`)で行う
  ——ライブラリは「測る対象に依存しない部分だけ」という既存方針([batch-uplink README](https://github.com/nna774/batch-uplink))通り、時刻を返すところまでに留めた。

## 発見された制約

- batch-uplinkの新しいgetterに依存するため、`v1.2.0`タグが切られるまでこの変更は
  ビルドできなかった。マージ→タグ切り後、`lib_deps`/`UPLINK_VERSION`を`v1.2.0`に
  上げて`pio run -e adxl355`が成功することを確認した。

## 新たに確認できた事実

- `lib_deps`/`UPLINK_VERSION`を`v1.2.0`に上げてビルド成功、`pytest`(lambda/tools)
  111件も引き続きpass。

## 新たに確認できた事実（続き）

- device2実機に書き込み・起動・WiFi再接続・送信再開まで確認済み
  （2026-08-05、age_s≈6.2秒・lag_s≈22.4秒・online=true）。

## 次に何が可能になったか

画面レイアウト自体（`buf:675 168m`のような長い文字列が右下90pxパディングに
収まるか）は、書き込み直後はbacklog=0（IP表示のまま）だったため未確認。
次に実際に欠測・バックログが発生した時に目視確認する。
