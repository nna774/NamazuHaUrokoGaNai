# データ遅延の誤検知バグを修正し、batch-uplink v2.14.0へ追従した

## 何を決めたか

`memo.md`にあった「batch RAMを最新先に送ってからspillの古いのを送るようになった。
watchdogの遅延判定がおかしい気がする」という懸念を調査し、実際にバグと確定して直した。

`batch-uplink` v2.11.0（[log/2026-08-11-uploader-task-split-design.md](2026-08-11-uploader-task-split-design.md)
の前段、`pump()`の送信優先順位をRAMキュー優先へ変更したコミット）以降、backlog処理中は
「RAM(最新)→spill(古い)→RAM(最新)→spill(古い)…」と新旧のバッチが交互にingestへ届く。
`batch_uplink/devices.py`の`record_batch()`が`last_batch_start_us`を無条件`SET`で
上書きしていたため、spillバッチ受信のたびにこの値が過去へ戻っていた。

このフィールドはwatchdogのデータ遅延判定(`devices.evaluate_lag()`、既定10分以上遅れで
通知)とdashboardの「データ鮮度」表示の両方で使われている。つまりbacklog処理中は
「データ遅延」通知と「解消」通知を交互に誤って出しうる状態だった。

`batch-uplink`側（[PR #23](https://github.com/nna774/batch-uplink/pull/23)、タグ`v2.14.0`）で
`last_batch_start_us`をConditionExpressionによる単調増加に変更し、`firmware/platformio.ini`
（2箇所: `[env:esp32dev]`・`[env:piezo]`）と`terraform/build_lambda.sh`の`UPLINK_VERSION`を
`v2.14.0`へ揃え、Lambda(ingest/api/watchdog/detect)を再デプロイした。

## なぜそう決めたか

`record_batch()`のdocstringには元々「バックフィル中は一時的に巻き戻り得るが、これは
表示上の『データ鮮度』であって生存判定には使わないので許容する」とあった。しかし
「生存判定(offline)には使わない」だけで、実際には「データ遅延判定(lag)には使う」ことを
見落としていた。生存(`last_ingest_at_us`)とデータ遅延(`last_batch_start_us`)を分離した
設計意図（バックフィル対策でどちらも壊さない）は正しかったが、後者の単調性が
RAM優先送信の変更で崩れていたことに気づかれていなかった。

単調増加にする対象を新フィールドへ分けず`last_batch_start_us`自体の定義を直した
（`record_batch()`のUpdateItemを2本に分割: 受信系フィールドは無条件更新、
`last_batch_start_us`だけConditionExpressionで守る）。理由は、dashboardの
「データ鮮度」表示も同じ巻き戻り問題を抱えており、人間が見る鮮度表示としても
「直近1回のPOSTがたまたま何時のバッチだったか」ではなく「これまでに把握した
最新のデータ時刻」の方が正しい意味論だったため。バックログの吐き出し進捗を見る
需要は`X-Namz-Spill-Count`/`X-Namz-Ram-Queued`ヘッダ(CloudWatch)で別に確保されており、
巻き戻る生の値を残す理由が無かった。

## 何が覆ったか

`batch_uplink/devices.py`の`record_batch()`docstringにあった「巻き戻りを許容する」
という前提を撤回した。

## 次に何が可能になったか

`terraform apply`済み・実機(device1)からの受信継続・`/devices`のAPI応答を確認済み。
backlog発生時（WiFi断からの復旧直後等）に「データ遅延」の誤通知が出なくなったはずだが、
実際にbacklogが溜まる状況（長めのWiFi断）でこの修正後の挙動を確認できてはいない。
次に長時間のWiFi断が発生した際、watchdogの遅延通知が誤発火しないことを実機で確認する。
