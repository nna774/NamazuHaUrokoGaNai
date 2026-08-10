# デバイス詳細APIのルーティング正規表現がuint32のdevice_idを弾いていたのを直す

## 何を決めたか

`lambda/api/handler.py`の`/devices/<id>`・`/devices/<id>/temp`ルートのパス正規表現を
`\d{1,4}`から`\d{1,10}`に広げた。テスト用device_id `4294967295`（=uint32最大値の
0xFFFFFFFF）はダッシュボードの一覧には出るのに、詳細ページを開くと404になっていた。

## なぜそう決めたか

`\d{1,4}`は「実運用の機体番号は高々4桁（9999まで）」という前提で書かれていたが、
device_idの実際の型はuint32であり4294967295（10桁）のような値も取りうる。一覧側の
`_devices()`はパスにIDを埋め込まず全件をDynamoDB Scanで返すためこの制限を踏まないが、
詳細側の`_device()`/`_device_temp()`はパスから正規表現でIDを取り出すため、10桁の
sentinel値が「どのルートにもマッチしない」→最後のcatch-allで404、という食い違いが
起きていた。

uint32の最大値は10桁なので`\d{1,10}`で全域をカバーできる。桁数以上の妥当性
（実在するdevice_idかどうか）はこれまで通り`devices.get_device()`がNoneを返すことで
別途404になるので、正規表現側は「パースできる範囲」だけ広げれば十分。

## 何が可能になったか

`https://namazu.dark-kuins.net/#device/4294967295`のような10桁device_idの詳細ページが
開けるようになった。回帰防止に`lambda/tests/test_api_devices.py`へ
`handler()`を直接叩くテストを追加（旧正規表現では404になることを確認済み）。
pytest（lambda/tests）112件通過。ブラウザでの実地確認はまだ。
