# lambda — 受信・検知・API

Python。計測震度は `tools/jismo`（FFT版・numpyのみ）を共有する。

## 関数

| 関数 | トリガ | 役割 |
|------|--------|------|
| `ingest` | Function URL | バッチPOSTを S3 raw/ へ保存。`/alert` はデバイス速報→即Slack通知 |
| `detect` | S3 ObjectCreated(raw/*) | 直近窓を再解析し地震を確定検知→events/コピー・DynamoDB・確定報通知 |
| `api`    | Function URL | ダッシュボード向け読み取り（波形・イベント）。認証なし・CORS許可 |

## 共通モジュール (`common/`)

| module | 内容 |
|--------|------|
| `wire.py`        | バッチのバイナリ形式パース（firmware WireFormat.h と一致） |
| `auth.py`        | HMAC-SHA256 検証 |
| `s3util.py`      | S3キー組み立て・時間範囲の列挙 |
| `store.py`       | raw/ からバッチを読み時間窓を連結 |
| `detect_core.py` | 検知の純関数（jismo使用・副作用なし・バックテスト可能） |
| `events.py`      | DynamoDBイベント管理（デバイス速報とクラウド確定報の突合・重複排除） |
| `notify.py`      | Notifier差し替え（Slack初期実装。Discord等を足すなら from_env に分岐追加） |

## 環境変数

| 変数 | 用途 |
|------|------|
| `NAMZ_BUCKET` | データ用S3バケット |
| `NAMZ_EVENTS_TABLE` | イベントのDynamoDBテーブル |
| `NAMZ_HMAC_SECRET` / `NAMZ_HMAC_SECRET_<id>` | デバイス共有鍵 |
| `NAMZ_SLACK_WEBHOOK_URL` | Slack Incoming Webhook |
| `NAMZ_NOTIFIER` | 通知種別（既定 slack） |
| `NAMZ_DETECT_WINDOW_S` / `_THRESHOLD` / `_HOLD_S` | 検知パラメータ |

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
