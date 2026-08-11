# イベント詳細APIがuint32最大値のdevice_idを400で拒否する不具合の修正

## 何が起きたか

テスト機(device_id=4294967295, uint32最大値、`tools/devices.json`参照)のイベント
`https://namazu.dark-kuins.net/#event/4294967295-59546597?...` を開くと、ダッシュボードが
400を返された。

原因は`lambda/api/handler.py`の`_event()`にあった。event_idの書式検証が
`re.fullmatch(r"\d{4}-\d{1,16}", eid)`で、device_id部分を**ちょうど4桁**に限定していた。
一方`lambda/common/events.py`の`event_id()`は`f"{device_id:04d}-{...}"`で「**最低4桁**
ゼロ埋め」なので、5桁以上のdevice_id（今回は10桁）だとevent_idもそのまま10桁になり、
4桁固定の正規表現に落ちて400になる。

デバイス詳細ルート(`/devices/(\d{1,10})`)は同種の問題を先に踏んで`\d{1,10}`へ直して
あった（`lambda/tests/test_api_devices.py`の`test_handler_routes_device_ids_beyond_four_digits`）
のに、`_event()`側だけ直っていなかった。

## 対処

`_event()`の正規表現を`\d{4,10}-\d{1,16}`に変更した。下限を4のままにしているのは
`event_id()`が`:04d`で必ず最低4桁ゼロ埋めする形式だから（device詳細ルートの生の
device_id整数とは違い、`0001`のような1桁未満の値は原理的に発生しない）。

回帰テストを`lambda/tests/test_api_event.py`に追加した
（`test_event_accepts_uint32_max_device_id`）。DynamoDB/S3への実アクセスを避けるため
`api.events.get_event`と`api.s3`(NoSuchKeyを返すfake)をmonkeypatchしている。

## 確認したこと

- `pytest lambda/tests`(121件)が全通過
