# リモート再起動 作戦（未実装）

コマンドラインからデバイスに再起動を要求し、デバイスがバッチ送信をした時にそれを
検知して自分で再起動する機能。[memo.md](../memo.md) 発の要望。2026-08-06 時点で
**未着手**（[STATUS.md](STATUS.md) の残タスクへ追加予定）。

用途: device 1 が watchdog timer に殺されてインターネット不調時に落ちる問題への
遠隔対応、および将来 [OTA更新](ota.md) を入れた後の「新ファーム起動確認→
問題があれば手動で切り戻すまでの間、遠隔で再起動を試せる」運用の足場。

## 採用する経路: バッチ送信レスポンスへの便乗

デバイスは30秒ごとに `Uploader::postBatch` でバッチを送っている。この送信の
レスポンスに「再起動要求あり」を乗せ、デバイス側は次にバッチを送ったタイミングで
気づいて自分で再起動する。専用のポーリングエンドポイントを別に立てる案もあったが、
今回は「送信のたびに確認する」という memo.md の要望どおりの形を選んだ。

### 構成要素と変更箇所

| リポジトリ | 変更 |
|---|---|
| [batch-uplink](https://github.com/nna774/batch-uplink)（Python） | `devices.py` に `request_restart(device_id)` / `clear_restart_request(device_id)` を追加。`get_device()` の返り値に含まれる `pending_restart` 相当の属性を ingest 側で読めるようにする |
| batch-uplink（C++） | `Uploader::postBatch` がレスポンスヘッダを読み、結果を呼び出し側へ伝えるようにする。**Electabuzz とも共有するので「再起動」という意味づけは持たせず、「指定したレスポンスヘッダの値を1つ読んで返す」汎用APIとして実装**し、`X-Namz-Restart` の解釈は `firmware/src/main.cpp` 側に置く。`dropOldestWhenFull`（[log/2026-08-05-device2-spill-overflow.md](log/2026-08-05-device2-spill-overflow.md)）と同じく**オプトイン**にし、Electabuzz側の既定動作は変えない |
| batch-uplink | 上記2つを入れた新タグを切る（現在pin中の `v1.2.0` の次、`v1.3.0` 想定） |
| このレポ `firmware/platformio.ini` | `lib_deps` のpinを新タグへ上げる |
| このレポ `terraform/build_lambda.sh` | `UPLINK_VERSION` を同じ新タグへ上げる（**2箇所を必ず揃える**。ずれると「何も変えていないのに壊れる」を踏む。CLAUDE.mdの不変条件） |
| このレポ `lambda/ingest/handler.py` | `_handle_batch`（現状 L55-71）で `devices.get_device()` を読み、`pending_restart` が立っていれば `_resp()` のレスポンスヘッダに `X-Namz-Restart: 1` を追加してから `devices.clear_restart_request()` を呼ぶ |
| このレポ `tools/request_restart.py`（新設） | `tools/flag_event.py` と同型（boto3で `namz-devices` テーブルを直更新、`--yes` 確認プロンプト、`awsenv.ensure_region()`）。`python tools/request_restart.py <device_id>` で要求を立てる |
| このレポ `firmware/src/main.cpp` | ヘッダ経由で再起動要求を受け取ったら、安全な再起動シーケンス（後述）を実行 |

### 一回性（ACK）の設計

要求は「一度伝えたら消す」。ingest がレスポンスヘッダに `X-Namz-Restart: 1` を
含めた**直後**に `namz-devices` の `pending_restart` をクリアする。デバイス側が
実際に再起動できたかどうかまでは追跡しない。

割り切り: レスポンスが途中で失われた（HTTPは投げたがデバイスがヘッダを読む前に
切れた等）場合、要求は消えたのに再起動されない不整合が起き得る。デバイス側から
明示ACKを往復させる案もあるが、今回は起きても実害が小さい（手元で
`request_restart.py` を打ち直せばよいだけ）ので取りこぼし許容にする。

### firmware側の安全な再起動シーケンス

`Uploader` の不変条件は「**2xxが返るまでバッチを捨てない**」
（`Uploader.h` 冒頭コメント）。再起動要求を受け取っても即 `ESP.restart()` せず、
送信タスク（Core0, `uploaderTask`）内で:

1. `Uploader::ramQueued()` / `spillCount()` が両方 0 になる（未送信分を出し切る）
   まで通常どおり `pump()` を回し続ける
2. 出し切ったら `esp_task_wdt_reset()` を挟みつつ後片付け
3. `ESP.restart()`

測定タスク（Core1, 優先度10, `samplingTask`）は特別扱いしない。プロセス全体が
再起動するので最終的に一緒に落ちる。

**task watchdog（10秒タイムアウト、`main.cpp` 起動時設定）に注意。**
`uploaderTask` の既存コメントに「TLSハンドシェイクが5秒×複数回続いてwdtの10秒を
超えてpanicした実績」が明記されている。再起動待機中もブロッキング処理の前後で
`esp_task_wdt_reset()` を挟むこと。

### 検証方法

正常な再起動なら30〜40秒（次のバッチ送信＋ブート）で復帰するので、watchdog Lambda
の欠測通知（既定300秒）は鳴らない。鳴ったら再起動シーケンス自体が失敗している
ということ（OTAの落とし穴と同じ考え方、[ota.md](ota.md) §3参照）。

## 着手時に決めること

- `namz-devices` テーブルへの属性追加（`pending_restart_requested_at_us` 等）と
  そのマイグレーション（既存項目には無いので `get_item` 側で欠損を正しく false 扱いする）
- batch-uplink 側 `Uploader::postBatch` の返り値/コールバックのシグネチャ
  （Electabuzz側の利用箇所も壊さない後方互換な足し方にする）
- `tools/request_restart.py` の対象指定（device_id 単体か、複数一括か。
  `flag_event.py` の `--before` のような拡張が要るかは現状不要と思われる）
