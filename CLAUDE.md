# CLAUDE.md — このリポジトリで作業するAIエージェント向けの案内

自宅地震計 NamazuHaUrokoGaNai。IIS3DHHC 加速度センサ + ESP32 で100Hz測定し、
気象庁の計測震度算出法で揺れを評価する。測定→送信→保存→検知→通知→可視化の全経路が
実機で稼働中。

このファイルは毎セッション自動で読まれる。**まず下の「ドキュメントの歩き方」で
該当ドキュメントに飛べ**。全体をコードから読み直す必要はない。

## ドキュメントの歩き方

| 知りたいこと | 読むファイル |
|--------------|--------------|
| 全体像・データフロー・ディレクトリ構成 | [README.md](README.md) |
| 設計判断の理由（サンプリング/震度アルゴリズム/信頼性/S3レイアウト） | [docs/design.md](docs/design.md) |
| いま何がどこまで動いているか・実機の検証結果・ハード配線 | [docs/STATUS.md](docs/STATUS.md) |
| 最初の実装計画とユーザーの決定事項 | [plan.md](plan.md) |
| バッチのバイナリ形式 | [docs/wire_format.md](docs/wire_format.md) |
| 各領域の詳細 | `firmware/` `lambda/` `terraform/` `dashboard/` `tools/` の各 `README.md` |

`memo.md` はユーザーの作業メモ（TODO・思いつき）。要件の出所になることがあるが、
コミット対象ではない。

## 構成（詳細は README.md）

`firmware/`(ESP32) `lambda/`(ingest/detect/api・Python) `terraform/`(AWS)
`dashboard/`(vanilla JS SPA) `tools/`(震度計算・解析・運用CLI・Python)。

## 知っておくべき不変条件

- **計測震度ロジックの単一の真実は `tools/jismo/`**。detect Lambda はこれを共有し、
  ファームのC++実装(`firmware/lib/Shindo`)は `tools/backtest.py` で数値照合してから使う。
- **イベントのデータモデル**（DynamoDB `namazu-events`、[lambda/common/events.py](lambda/common/events.py)）:
  - `device_prompt` … デバイス速報が来た / `cloud_confirmed` … クラウドFFTで確定
  - `checked` … detectが評価済み（未確定なら一覧の既定で隠れる=非該当）
  - `artificial` … 人工地震(テスト等)フラグ。立てると一覧の既定で隠れ、`all=1` でのみ薄く出る
  - 一覧の既定フィルタは「(確定 or 未評価) かつ 非artificial」。表示震度は `effective_intensity`。
- **欠測監視**（データが来ないこと自体の検知。DynamoDB `namazu-devices`、
  [lambda/common/devices.py](lambda/common/devices.py)）:
  - 生存の主信号は `last_ingest_at_us`（ingestが**受信した壁時計時刻**）。firmwareは
    WiFi断のあとバックフィルするので、測定時刻(`last_batch_start_us`)だけでは
    「復旧直後の追いつき中」と「本当に沈黙」が区別できない。生存は受信壁時計で見る。
  - `watchdog` Lambda(EventBridge定期起動)が最終受信からの経過を見て欠測をSlack通知。
    落ちている間は `NAMZ_OFFLINE_RENOTIFY_S`(既定1日)ごとに再送、受信再開で復帰通知。
    欠測状態(`offline_notified_at_us`)は watchdog だけが書き、ingestの受信系フィールドとは
    互いに素なのでUpdateItemで分ければ競合しない。状態遷移は `devices.evaluate()` に集約。
- **api Lambda(Function URL)は認証なし・読み取り専用**。書き込み(フラグ操作等)は手元から
  DynamoDBを直接更新する `tools/flag_event.py` で行う。api は `/devices`・`/devices/<id>` で
  デバイス生存も返す。
  - **「人工地震にして」と言われたら既定で `--confirmed-only` を付ける**。未確定は一覧の
    既定フィルタで元々隠れるので、フラグを立てる意味があるのは確定済みだけ。「非確定も
    全部」と明示された時だけ外す。

## デプロイ手順（AWS: リージョン ap-northeast-1 / project=namazu）

terraform state はS3バックエンド(`nana-terraform-state`)。AWS認証情報はこのマシンの
`aws` CLI 設定をそのまま使う(`aws sts get-caller-identity` が通ればOK)。リージョンは
`AWS_REGION=ap-northeast-1`。詳細は [terraform/README.md](terraform/README.md#認証情報statetfvars)。

```bash
# Lambda（common/ を触ったら detect と api の両方に効く）
PYTHON=./.venv/bin/python terraform/build_lambda.sh      # zip を builds/ に生成（apply前に必須）
cd terraform && AWS_REGION=ap-northeast-1 terraform apply

# ダッシュボード（app.js/index.html を触ったら）
cd dashboard && aws s3 sync . "s3://$(cd ../terraform && terraform output -raw dashboard_bucket)/" \
  --exclude 'config.example.js' --exclude 'README.md'
aws cloudfront create-invalidation \
  --distribution-id "$(cd ../terraform && terraform output -raw dashboard_distribution_id)" \
  --paths '/app.js' '/index.html'
```

`config.js` は本番APIのURL(`https://api.namazu.dark-kuins.net`)が入る。sync対象なので消すな。
カスタムドメインまわりの順序は [terraform/README.md](terraform/README.md) を参照。

## 開発の約束（グローバル設定に加えて）

- コミットは日本語・意味単位。rebaseせず master を merge。テストは `.venv` で
  `pytest lambda/tests` / `pytest tools/tests`。
