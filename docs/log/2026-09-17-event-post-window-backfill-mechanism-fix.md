# イベント保存範囲のPOST側後追いバックフィルが確定検知イベントで機能していなかったバグを直す

## 発端

[茨城県南部M4.8(2026-09-17 00:07)の事後解析](2026-09-17-ibaraki-nanbu-m4.8-post-hoc-detection.md)で
ユーザーから「保存範囲が00:10:19までしかない、200秒で切れてすぐでは」と指摘され調査したところ、
実際に`events/0001-59652376/`のS3オブジェクトはonsetから約123秒ぶんしかコピーされておらず、
`POST_SECONDS=600`（10分）の看板と大きく食い違っていた。

## 原因

`lambda/detect/handler.py`の`_confirm()`（STA/LTAが閾値を超えている間、stride(30秒)ごとに
再発火する）は、発火のたびに`onset-180秒〜onset+600秒`の範囲でraw batchをコピーしようとするが、
**その時点でS3のraw/に実在するファイルだけ**しかコピーできない——地震発生直後の再発火では、
未来の600秒ぶんのバッチはまだアップロードされていない。

本来この取りこぼしは`_preserve_prompt_waveforms()`（onsetから`POST_SECONDS`経過後に一度だけ
全区間を後追いコピーする関数）が拾うはずだったが、ガード条件が`item.get("waveform_prefix")`の
有無を見ており、`_confirm()`が初回コピー直後に無条件でこのフラグを立てるため、**確定検知
(`cloud_confirmed`)したイベントはこの後追いから永久に除外されていた**。揺れが閾値を割って
`_confirm`の再発火が止まった時点で、それ以上コピーが進む経路が無くなる。

## 影響範囲の確認

DynamoDBを全scanして`cloud_confirmed=true`の74件を調べたところ、68件は`artificial=true`
（設置作業中の振動試験等、[2026-08-30のログ](2026-08-30-event-pre-window-backfill.md)で
既に把握・除外判断済み）で対象外と判明。残る非artificial・非manualの6件（3地震ぶん:
`59580602`=M5.9・`59600556`=千葉県東方沖M4.9・`59652376`=今回）のうち、M5.9は2026-08-23に
別件（meta.json上書きバグ）のバックフィルで結果的にPOST側も延長済みだったが、**千葉県東方沖
M4.9（`0001/0002-59600556`）はPRE側のみ2026-08-30に延長されPOST側は未処理のまま残っていた**
（[該当ログ](2026-08-30-event-pre-window-backfill.md)は「終端側は変更せず」と明記）。

`0001/0002-59600556`・`0001/0002-59652376`とも`store.copy_raw_to_event`でraw batchを
onset+600秒まで追加コピーし、`meta.json`をその区間で再計算して上書き（DynamoDBの
`confirmed_intensity`等は触っていない。震度・ピーク値は再計算後も一致し、想定通りコーダの
取りこぼしは無かった）。CloudFront `/event?id=<eid>`のinvalidationも実施。

## 修正

`_preserve_prompt_waveforms`・`_copy_event_waveforms`・`_merge_meta`・`_put_meta`を
`lambda/detect/handler.py`から`lambda/common/event_backfill.py`へ切り出し、判定条件を
`waveform_prefix`の有無から専用の`waveform_backfilled`フラグへ変更した
（`manual`は対象外、`device_prompt`か`cloud_confirmed`のどちらかが立っていて
`waveform_backfilled`が未設定なら対象）。

さらに、この判定は「onsetから時間が経過したか」という条件だけで揺れの継続に依存しないが、
**実行される経路自体は生バッチ到着に便乗している**——ユーザーから「揺れが収まった後の
平坦な波形ではdetectから何も入ってこないのでは」と指摘を受け検証した。`_process()`内で
`event_backfill.backfill_pending_events()`を呼ぶ行はSTA/LTA再評価の`if`の外にあり、
揺れの有無に関わらず生バッチ到着のたび毎回実行される（ファーム側のバッチ切り出しも
固定30秒間隔で振幅を見ていない）ため、実際には揺れが収まった後も通常運用のバッチ到着で
即座に埋まるはずだが、**ingest自体が止まった場合（強い揺れが停電・WiFi断を引き起こす
ケースなど）はこの経路も止まる**。`watchdog`Lambda（EventBridgeで`rate(5 minutes)`定期起動、
既に「イベント駆動では検知できない不在」を扱うために存在する）から同じ`backfill_pending_events`を
壁時計時刻で呼ぶようにし、ingestの状況に依存しない保険を追加した。

## テスト

`_merge_meta`のテスト（`lambda/tests/test_detect_meta_merge.py`）を
`lambda/tests/test_event_backfill.py`へ移し、`needs_backfill`（バックフィル対象判定の
純粋関数として切り出した）のテストを追加: cloud_confirmedイベントが対象に入ること
（バグの再現ケース）、`waveform_backfilled`済み・`manual`・条件不足（device_prompt/
cloud_confirmedどちらも無し）・時間経過不足・1時間超過で諦める、の各分岐を確認した。

## 次に必要な作業

コードの修正はデプロイ済みではない。`terraform/build_lambda.sh` → `terraform apply`で
detect・watchdog両Lambdaへ反映する必要がある。
