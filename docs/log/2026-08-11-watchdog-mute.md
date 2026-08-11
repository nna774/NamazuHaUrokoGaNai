# watchdogのmute機能を追加した

## 何を決めたか

`namazu-devices`にデバイス単位の`watchdog_muted`フラグを追加した。

- mute中は`lambda/watchdog/handler.py`が評価ループの先頭でそのデバイスを丸ごと
  スキップする。欠測・データ遅延・pull型OTA停滞、どの通知も出ない。
- ingest(`lambda/ingest/handler.py`)がバッチを1本受信するたび、無条件で
  `watchdog_mute.clear_mute()`を呼んで自動unmuteする（mute中でなければ何も
  起きない）。
- 手元操作は`tools/mute_device.py mute/unmute/list`（`tools/request_restart.py`
  と同じ形のCLI）。
- 判定ロジックは`lambda/common/watchdog_mute.py`の`is_muted()`に切り出し、
  `devices.evaluate()`や`ota_watch.evaluate_ota_stuck()`と同じく副作用抜きで
  テストできるようにした。

## なぜそう決めたか

`tools/devices.json`のテスト機(device_id=4294967295, fake-sensor基板)はハード
試験のたびに繋いでは終わったら電源を切る、という使われ方をする。watchdogは
「最終受信からの経過」だけを見るので、試験後に黙ると必ず「欠測」判定になり、
`NAMZ_OFFLINE_RENOTIFY_S`(既定1日)ごとに再送し続けて無意味に鳴り続けていた。

一方で「試験中に本当に落ちた」場合は気付きたい——単純に監視対象から外す
（`namazu-devices`の項目を消す等）と、試験中の異常も無音になってしまう。

そこで「試験を始めて実際にデータが送られてきたら自動でunmuteする」設計にした。
これなら:

- 試験を始める（＝バッチが届き始める）と自動で監視が復帰し、試験中に落ちれば
  通常通り通知が来る。
- 試験が終わって黙ったら、まず1回だけ「欠測」通知が来る（むしろ「試験が終わった
  はず」の目印になる）。そこで手元CLIで再度muteすれば、次に繋ぐまで静かになる。
- 次回試験時にunmuteし忘れる心配が無い（データが来た時点で自動的に外れる）。

これは`docs/STATUS.md`に残っていた「デバイスの退役後、watchdogが延々と欠測通知
しないようにする運用を決める」という未着手タスクの実装でもある。退役デバイスにも
同じ仕組みがそのまま使える（そちらは単に二度とunmuteされないだけ）。

## 何が覆ったか

`docs/STATUS.md`の残タスク「デバイスの退役（引退）手順を考える」を実装済みに
更新した。

## 次に何が可能になったか

`tools/mute_device.py mute 4294967295`で試験後の再送スパムを止められる。
デプロイ(`terraform/build_lambda.sh` → `terraform apply`)後、実機試験で
「試験中に電源を抜いたら通知が来る／試験後に黙っても1回で止まる」ことを
実機で確認する。

## 追記: ダッシュボード表示（同日）

mute中の機体をダッシュボードの「デバイス」タブで開くと、実際は受信が
途絶えているのに「● オンライン」（`age_s`が新しければ）や「● 欠測」
（古ければ）とだけ出て、意図的に黙らせている状態だと分からなかった。

- `lambda/api/handler.py`の`_device_view()`に`watchdog_muted`
  (`watchdog_mute.is_muted(item)`)を足し、`/devices`・`/devices/<id>`の
  両方のレスポンスに載せた。
- `dashboard/app.js`に`deviceStatusHtml(d)`を切り出し、`watchdog_muted`が
  立っていれば`online`の真偽に関わらず灰色「● 監視停止」を優先表示する
  ようにした（一覧・詳細ページ両方でこのヘルパーを共有）。
- 一覧上部のサマリからもmuted中のデバイスを「欠測」件数から除外し、
  「監視停止 N台」として別カウントで出す（意図的に黙らせているだけで
  対処が要る状態ではないため、欠測件数に混ぜると紛らわしい）。
- ラベル文言は「mute」をそのままカタカナにするか迷ったが、
  `lambda/common/watchdog_mute.py`・`tools/mute_device.py`のコード内
  コメント/CLI出力が既に「監視対象外」「監視停止」寄りの日本語で
  統一されていたため、ユーザーに候補（監視対象外／ミュート中／監視停止）
  を提示して選んでもらい、「監視停止」に決定した。色は人工地震バッジ
  (`badge-art`)と同じ灰(#888)を流用し、「意図的に抑制している状態」を
  視覚的にも揃えた。
