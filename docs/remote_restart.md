# リモート再起動

コマンドラインからデバイスに再起動を要求し、デバイスがバッチ送信をした時にそれを
検知して自分で再起動する機能。[memo.md](../memo.md) 発の要望。2026-08-06 に実装した
（batch-uplink [v1.3.0](https://github.com/nna774/batch-uplink/releases/tag/v1.3.0)）。

用途: device 1 が watchdog timer に殺されてインターネット不調時に落ちる問題への
遠隔対応、および将来 [OTA更新](ota.md) を入れた後の「新ファーム起動確認→
問題があれば手動で切り戻すまでの間、遠隔で再起動を試せる」運用の足場。

## 使い方

```bash
export NAMZ_DEVICES_TABLE=namz-devices   # or --table

python tools/request_restart.py request 1   # device 1 に再起動要求を立てる
python tools/request_restart.py cancel 1    # まだ反映されていなければ取り消す
python tools/request_restart.py list        # 要求が立っているデバイスを一覧
```

要求を立てると、そのデバイスが次にバッチを送信した時（既定30秒周期）に気づき、
未送信キューを出し切ってから自分で再起動する。正常なら30〜40秒（次のバッチ送信＋
ブート）で復帰するので、watchdog Lambda の欠測通知（既定300秒）は鳴らない。鳴ったら
再起動シーケンス自体が失敗しているということ（OTAの落とし穴と同じ考え方、
[ota.md](ota.md) §3参照）。

## 採用した経路: バッチ送信レスポンスへの便乗

デバイスは30秒ごとに `Uploader::postBatch` でバッチを送っている。この送信の
レスポンスに「再起動要求あり」を乗せ、デバイス側は次にバッチを送ったタイミングで
気づいて自分で再起動する。専用のポーリングエンドポイントを別に立てる案もあったが、
「送信のたびに確認する」という memo.md の要望どおりの形を選んだ。

### 構成要素と変更箇所

| リポジトリ | 変更 |
|---|---|
| [batch-uplink](https://github.com/nna774/batch-uplink)（Python） | `devices.py` に `request_restart(device_id, at_us)` / `clear_restart_request(device_id)` を追加（[PR#3](https://github.com/nna774/batch-uplink/pull/3)）。台帳の属性は `pending_restart_requested_at_us` |
| batch-uplink（C++） | `Uploader` に `watchResponseHeader`（既定 `nullptr`）をオプトインで追加。設定するとバッチPOST成功時にそのレスポンスヘッダの値を `lastResponseHeaderValue()` で読める。**Electabuzz とも共有するので「再起動」という意味づけは持たせず、「指定したレスポンスヘッダの値を1つ読んで返す」汎用API**。`X-Namz-Restart` の解釈は `firmware/src/main.cpp` 側に置く。`dropOldestWhenFull`（[log/2026-08-05-device2-spill-overflow.md](log/2026-08-05-device2-spill-overflow.md)）と同じ考え方 |
| batch-uplink | `v1.3.0` タグ |
| このレポ `firmware/platformio.ini` / `terraform/build_lambda.sh` | pin を `v1.3.0` へ（2箇所を必ず揃える。CLAUDE.mdの不変条件） |
| このレポ `lambda/ingest/handler.py` | `_handle_batch` で `devices.get_device()` を読み、`pending_restart_requested_at_us` が立っていれば `_resp()` のレスポンスヘッダに `X-Namz-Restart: 1` を追加してから `devices.clear_restart_request()` を呼ぶ |
| このレポ `tools/request_restart.py` | `tools/flag_event.py` と同型（boto3で `namz-devices` テーブルを直更新、`--yes` 確認プロンプト、`awsenv.ensure_region()`）。`request`/`cancel`/`list` のサブコマンド |
| このレポ `firmware/src/main.cpp` | `gUploader` に `watchResponseHeader="X-Namz-Restart"` を渡し、`uploaderTask`（Core0）でヘッダ値を監視。安全な再起動シーケンス（後述）を実行 |

### 一回性（ACK）の設計

要求は「一度伝えたら消す」。ingest がレスポンスヘッダに `X-Namz-Restart: 1` を
含めた**直後**に `pending_restart_requested_at_us` をクリアする。デバイス側が
実際に再起動できたかどうかまでは追跡しない。

割り切り: レスポンスが途中で失われた（HTTPは投げたがデバイスがヘッダを読む前に
切れた等）場合、要求は消えたのに再起動されない不整合が起き得る。デバイス側から
明示ACKを往復させる案もあるが、起きても実害が小さい（手元で
`request_restart.py request` を打ち直せばよいだけ）ので取りこぼし許容にした。

### firmware側の安全な再起動シーケンス

`Uploader` の不変条件は「**2xxが返るまでバッチを捨てない**」
（`Uploader.h` 冒頭コメント）。再起動要求を受け取っても即 `ESP.restart()` せず、
送信タスク（Core0, `uploaderTask`）内で:

1. `restartRequested` フラグを立てるだけで、通常どおり `pump()` を回し続ける
2. 毎周のループで `Uploader::ramQueued()` / `spillCount()` が両方 0 になったのを
   確認したら（未送信分を出し切ったら）`esp_task_wdt_reset()` を挟みつつ `ESP.restart()`

測定タスク（Core1, 優先度10, `samplingTask`）は特別扱いしない。プロセス全体が
再起動するので最終的に一緒に落ちる。

**task watchdog（10秒タイムアウト、`main.cpp` 起動時設定）に注意。**
`uploaderTask` の既存コメントに「TLSハンドシェイクが5秒×複数回続いてwdtの10秒を
超えてpanicした実績」が明記されている。再起動直前も `esp_task_wdt_reset()` を
挟んでから `ESP.restart()` する。

## 実装状況

実装済み（このドキュメント上部の使い方参照）。**実機での動作確認はまだ**
（firmwareビルド[esp32dev/adxl355両env]・`pytest lambda/tests tools/tests`は確認済み）。
