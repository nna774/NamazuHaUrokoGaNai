# FakeSensor(結合試験用)のsensor_typeにも表示名を持たせる

## 何を決めたか

`lambda/common/wire.py`の`SENSOR_TYPE_NAMES`に`SENSOR_TYPE_FAKE = 255`（firmware
`FakeSensor::sensorType()`が返すsentinel値）を追加し、「ダミー」という表示名を付けた。

## なぜそう決めたか

4294967295番機（uint32最大値、newBatch()バッファプールの結合試験で使ったテスト機）の
詳細ページで「センサ」欄が空欄（`不明`）になっていたのを見て、ユーザーから「これって
今何か送ってるんだっけ」と聞かれた。DynamoDBの`namazu-devices`を直接引くと
`sensor_type: 255`が実際に記録されていた——FakeSensorは意図的に255（実チップの型番0/1
と衝突しないuint8_t最大値）を返しているので、**何も送っていない/未記録なのではなく、
「ダミーであること」を明示するヘッダを毎バッチ送っている**。ただし
`wire.SENSOR_TYPE_NAMES`が0/1しか知らなかったため、詳細ページ側では
「本当に未記録(古いファーム等)」と「意図的なダミー」が区別できず、どちらも
`不明`に潰れて表示されていた。

## 何が可能になったか

詳細ページの「センサ」欄が`不明`ではなく`ダミー`と出るようになり、実センサ未記録の
機体（旧ファーム等）と結合試験用のFakeSensor機を見分けられる。`lambda/tests/test_api_devices.py`
に`test_device_view_reports_fake_sensor_name`を追加。pytest（lambda/tests）113件通過。
ダッシュボードでの実地確認（`d.sensor || '不明'`が`ダミー`をそのまま出すだけなので
`dashboard/app.js`側の変更は不要）はデプロイ後に行う。
