# pull型OTA作戦の訂正: バイナリに秘密情報が生で入っている

[前回](2026-08-06-ota-pull-strategy-design.md)立てたpull型OTAの作戦（`ota/<env>/<version>.bin`
を1本CloudFrontで公開する）が、現状のファーム構成のままでは成立しないと判明した。
ユーザーから「バイナリに投稿用の鍵やSSID/パスワードは入っているか」と問われて確認した。

## 何を決めたか

`tools/provision_device.py`の`render_secrets_h`が生成する`firmware/src/secrets.h`は、
WiFi SSID/パスワード・デバイス固有のHMAC鍵(`kHmacSecret`)・ArduinoOTA認証パスワード
(`kOtaPassword`)を`static constexpr const char*`の文字列リテラルとして持つ。コンパイラは
これを暗号化・難読化しないので、焼いた`firmware.bin`には平文のまま入る
(`strings firmware.bin`で読める水準)。

pull型の配布物を「envごとに1本、不特定多数が読めるURLに置く」設計のままだと、
そのバイナリに焼き込まれた**特定の1台**のWiFiパスワード・投稿用HMAC鍵・OTAパスワードを
世界に公開することになる。push型（LAN内espota）は送り返す相手が秘密の持ち主自身
なので問題にならなかったが、pull型では話が違う。

対策方針として、アプリコード（env共通・公開可）とデバイス識別・秘密（デバイス固有・
非公開）を分離することにした。secrets.hのコンパイル時埋め込みをやめ、初回USB書き込み
時にNVSへ別途書き込む方式に変える。OTAはappパーティションのみを書き換えNVSには
触らないので、identity/secretsはOTAをまたいで保持される。

## 何が覆ったか

前回の作戦にあった「`ota/<env>/<version>.bin`を1本公開すれば足りる」という前提が
覆った。**秘密情報のNVS化がpull型実装の前提条件**として追加になった（pull型固有の
作業ではなく、pull型を作る前に先に終わらせておくべきタスク）。

## 次に何が可能になったか

`docs/ota.md`§7に前提条件として明記し、未決事項の先頭に追加した。次のセッションは
まずNVS化（`tools/provision_device.py`の払い出しフローへの組み込み方法を決める）から
着手できる。push型は現状のままでも実害は無いが、同じNVS化をしておけば一貫性が高く、
将来secrets.h自体を廃止できる見込みも書き添えた。

詳細は[ota.md §7](../ota.md#7-将来-httpsプル型作戦実装は未着手)を参照。
