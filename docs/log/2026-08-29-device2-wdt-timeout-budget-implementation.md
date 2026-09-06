# 2026-08-29 device2のWDT対処: 接続・ハンドシェイク・ヘッダ読み取りの合計を縮める実装

[2026-08-29-device2-wdt-panic-fix-direction.md](2026-08-29-device2-wdt-panic-fix-direction.md)
で決めた修正方針のうち、「各区間に明示的な締切を足す」を`batch-uplink`側に実装した
（別リポジトリ、[PR #27](https://github.com/nna774/batch-uplink/pull/27)）。

## 実装前に発覚した2つの見直し

### 項目1「`writeToStreamDataBlock`へのタイムアウト追加」は見送った——現状は到達しないデッドコード

前回のログでは「レスポンスボディ読み取り(`writeToStreamDataBlock`)にタイムアウト判定が
一切無い」ことを最優先の修正対象としていたが、`HTTPClient::sendRequest()`の実装
（`HTTPClient.cpp:585-707`）を読み直したところ、この関数は`handleHeaderResponse()`
（ヘッダ読み取り）の直後に`return`しており、ボディは`getString()`/`getStream()`/
`writeToStream()`を呼んだ時にしか読まれないと分かった。`Uploader::postBatch()`・
`Uploader::sendAlert()`はどちらも`http_.POST()`の戻り値(ステータスコード)と
`http_.header()`(ヘッダのみ)しか見ておらず、ボディを一切読んでいない。
**つまり`writeToStreamDataBlock`は現状のコードパスから一度も呼ばれない。**

`http_.end()`→`disconnect()`内の`_client->available()`チェックも、
`WiFiClientSecure::available()`が呼ぶ`mbedtls_ssl_read(ctx, NULL, 0)`1回だけ
(ソケットタイムアウトで頭打ち)で、`flush()`は`WiFiClientSecure`では空実装
(`WiFiClientSecure.h:65`、`void flush() {}`)——ここも無制限ループには当たらない。

実際にcoredumpで確認できたクラッシュも接続・ハンドシェイク段階（項目2の範囲）で
起きていたことと整合する。**今は起きないシナリオへの防御コードは書かない**方針
に沿い、項目1は見送った。将来`getString()`等を足す人向けの地雷として、
今回の変更のコミットメッセージ・PR本文に経緯を残してある。

### 副産物: レスポンスボディを読まずに接続を使い回す設計は、読み残しバイトの混入リスクを持つ

上記の調査中、別の潜在バグに気付いた。`postBatch()`はボディを一切読まないまま
`setReuse(true)`で接続を使い回している。ingest Lambda(`lambda/ingest/handler.py`
`_resp()`)は成功時も含め常にテキストボディを返すため、読み残された平文が
mbedtlsコンテキスト内に残ったまま次のリクエストへ持ち越される。次の
`postBatch()`が接続を再利用してヘッダを読もうとすると、前回の読み残しボディを
新しいレスポンスのステータス行として誤読しうる。

ただしメモリに無限に溜まるわけではない——mbedtlsの内部バッファは1TLSレコード分の
固定サイズで、次のレコードで上書きされるだけ。誤読で`code`がおかしくなれば
`ok=false`となり`postBatch()`の失敗パスで`client_.stop()`が呼ばれ、次回は
強制的に繋ぎ直されて状態はリセットされる。**自己修復はするが、その代償として
説明のつかない散発的なPOST失敗・バックオフが起きている可能性がある。**
今回のWDT対処とは独立した別バグなので、実装はせず`docs/design.md`未定事項に
既知の問題として書き足すに留めた。

## 実装内容（`batch-uplink`側、[PR #27](https://github.com/nna774/batch-uplink/pull/27)）

`Uploader.cpp`のタイムアウト定数を見直した。

- **接続タイムアウト(`http_.setConnectTimeout()`)を新規に明示設定: 3000ms**
  （既定値5000msのまま未設定だった）。TCP接続確立の`select()`を縛るだけでなく、
  `WiFiClientSecure::connect()`に渡ったこの値がハンドシェイク内部のソケット
  `recv()`/`send()`の`SO_RCVTIMEO`/`SO_SNDTIMEO`にもそのまま流用される
  （`ssl_client.cpp`の`start_ssl_client()`）ため、1箇所の変更で2区間に効く
- **ハンドシェイクタイムアウト(`setHandshakeTimeout()`)を4000ms→3000msへ短縮**
- **ヘッダ読み取りタイムアウト(`http_.setTimeout()`)を新規に明示設定: 3000ms**
  （既定値5000msのまま未設定だった。`handleHeaderResponse()`の無通信ギャップ判定に効く）

最悪合計は「接続3000 + (ハンドシェイク判定3000 + 内部recv一発3000) + ヘッダ3000」
＝12000msまで縮んだ。呼び出し側のWDT(20000ms)に対し8秒(40%)の余裕を持たせた。

`postBatch()`が使う使い回し接続(`http_`/`client_`、`Uploader::begin()`で1回だけ
設定)だけでなく、`sendAlert()`のローカル接続にも同じ3値を適用した——`sendAlert()`
も同じ`uploaderTask`（WDT登録済み）から呼ばれる同種のリスクを持つため。

DNS解決(`WiFi.hostByName()`)の締切は前回ログの通り今回も対象外のまま。

### 追記: 3値を`Uploader`のコンストラクタ引数として外から指定できるようにした

最初はファイル内の`static constexpr`3定数として実装したが、ユーザーから
「外から定義できないか、複雑になるか」と聞かれ検討した結果、この場でPR #27に
追加コミットして引数化した。`Uploader`は本レポ専用ではなく周波数モニタ
Electabuzzとも共有しているクラスで、呼び出し側のtask watchdog設定（ひいては
安全なタイムアウト予算の上限）はプロジェクトごとに異なりうる。コンストラクタは
既に`dropOldestWhenFull`・`caCert`・`maxSpillReadBytes`等12個のオプション引数を
持つ設計のため、`connectTimeoutMs`/`handshakeTimeoutMs`/`responseTimeoutMs`
（既定はいずれも3000、今回決めた値のまま）を追加しても複雑さは大きく増えない
と判断した。既存の呼び出し側は引数を省略すれば挙動は変わらない。

## コンパイル確認

`batch-uplink`のホストテスト(`test/run.sh`)は`Batch`/`NamzWire`のみが対象で
`Uploader.cpp`はカバーしない（Arduino/ESP32フレームワーク依存のため）。
代わりに`firmware/platformio.ini`の`lib_deps`を一時的に`symlink://`でこの
ブランチのworktreeへ向け、`pio run -e adxl355`のフルビルドが通ることを確認した
（引数化の前後で計2回。確認後`platformio.ini`は毎回元に戻した。既存呼び出し側は
新引数を省略しているため、コンストラクタのシグネチャ変更後もそのままビルドが
通ることも合わせて確認できた。実機フラッシュ・実機確認は未実施）。

## 次に何が可能になったか

- `batch-uplink` PR #27のマージ・バージョンタグ付け・`firmware/platformio.ini`と
  `terraform/build_lambda.sh`のUPLINK_VERSION更新（CLAUDE.mdの不変条件通り2箇所
  揃える）が残っている
- 実機(device2)へのOTA配信・実際にWDTパニックが収まったか（今度はパニックせず
  バックオフに落ちて`false`を返すログが出るか）の確認が要る
- 副産物で見つけた「読み残しボディによる接続使い回し時のヘッダ誤読」は未着手
  のまま`docs/design.md`未定事項に残した
- DNS解決の締切も引き続き未着手
