# lambda — 受信・検知・API

Python。計測震度は `tools/jismo`（FFT版・numpyのみ）を共有する。

## 関数

| 関数 | トリガ | 役割 |
|------|--------|------|
| `ingest` | Function URL | バッチPOSTを S3 raw/ へ保存。`/alert` はデバイス速報→即Slack通知 |
| `detect` | S3 ObjectCreated(raw/*) | 直近窓を再解析し地震を確定検知→events/コピー・DynamoDB・確定報通知 |
| `api`    | Function URL | ダッシュボード向け読み取り（波形・イベント・デバイス生存）。認証なし・CORS許可 |
| `watchdog` | EventBridge 定期 | 各デバイスの最終受信からの経過を見て欠測をSlack通知（1日ごと再送・復帰通知） |

## 共通モジュール (`common/`)

| module | 内容 |
|--------|------|
| `wire.py`        | バッチのバイナリ形式パース（firmware `lib/NamzWire/WireFormat.h` と一致） |
| `s3util.py`      | S3キー組み立て・時間範囲の列挙。20桁ゼロ埋めで辞書順＝時系列順になる命名（旧`batch_uplink.s3util`。Electabuzzは保存方針が違うため独自の`s3keys.py`を持っており実質共有されていなかったので引き上げた） |
| `store.py`       | raw/ からバッチを読み時間窓を連結 |
| `detect_core.py` | 検知の純関数（jismo使用・副作用なし・バックテスト可能） |
| `events.py`      | DynamoDBイベント管理（デバイス速報とクラウド確定報の突合・重複排除） |
| `quicklook.py`   | 確定報に添える波形クイックルックPNGの描画（detectのみ・Pillow使用） |
| `imagehost.py`   | PNGを公開URLに載せる配信層（Gyazo初期実装。S3等に替えるならここに分岐追加） |

## 共有ライブラリ (`batch_uplink`)

地震に依存しない部分は [batch-uplink](https://github.com/nna774/batch-uplink) に切り出して
周波数モニタ [Electabuzz](https://github.com/nna774/Electabuzz) と共有している。
`from batch_uplink import ...` で使う。**タグで pin する**（版は
[terraform/build_lambda.sh](../terraform/build_lambda.sh) の `UPLINK_VERSION`）。

| module | 内容 |
|--------|------|
| `auth.py`        | HMAC-SHA256 検証 |
| `devices.py`     | デバイス生存台帳（ingestが最終受信をupsert・watchdogが欠測判定・apiが読む） |
| `notify.py`      | Notifier差し替え（Slack初期実装。Discord等を足すなら from_env に分岐追加） |

手元でテストを回すには venv に入れておくこと。

```bash
.venv/bin/pip install --no-deps "git+https://github.com/nna774/batch-uplink@v1.0.0"
```

## 環境変数

| 変数 | 用途 |
|------|------|
| `NAMZ_BUCKET` | データ用S3バケット |
| `NAMZ_EVENTS_TABLE` | イベントのDynamoDBテーブル |
| `NAMZ_DEVICES_TABLE` | デバイス生存台帳のDynamoDBテーブル |
| `NAMZ_HMAC_SECRET` / `NAMZ_HMAC_SECRET_<id>` | デバイス共有鍵 |
| `NAMZ_SLACK_WEBHOOK_URL` | Slack Incoming Webhook |
| `NAMZ_NOTIFIER` | 通知種別（既定 slack） |
| `NAMZ_GYAZO_TOKEN` | Gyazoアクセストークン（scope `public`）。確定報に波形画像を添える。空なら画像なし（detectのみ） |
| `NAMZ_DETECT_WINDOW_S` / `_THRESHOLD` / `_HOLD_S` | 検知パラメータ |
| `NAMZ_DETECT_STRIDE_S` | 窓を再評価する刻み[秒]（detect・既定0=バッチ到着ごと）。0超なら「この刻みの境界を跨いだバッチ」だけが評価する |
| `NAMZ_OFFLINE_AFTER_S` | 欠測とみなす最終受信からの秒数（api/watchdog共通・既定300） |
| `NAMZ_OFFLINE_RENOTIFY_S` | 欠測継続中の再送間隔[秒]（watchdog・既定86400） |

## パッケージング

各関数のzipには `handler.py` と `common/`・`jismo/` を同梱する。
`terraform/build_lambda.sh` が `tools/jismo` をコピーして固める。

## テスト

```bash
cd .. && python -m venv .venv && . .venv/bin/activate
pip install numpy pytest
cd lambda && pytest tests/ -q
```

検証内容: ワイヤ形式のパース（firmwareのバイト列と一致）、gal換算、HMAC検証、
合成地震の検知・ノイズと単発スパイク（生活振動）の不検知。
