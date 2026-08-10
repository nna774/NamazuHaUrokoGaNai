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
| 実機のノイズ特性・検出限界・センサ選定の知見 | [docs/noise.md](docs/noise.md) |
| 震度算出の落とし穴（窓の違い・ドリフトと端の暴れ） | [docs/intensity_pitfalls.md](docs/intensity_pitfalls.md) |
| ADXL355機の追加計画（未着手） | [docs/adxl355.md](docs/adxl355.md) |
| ファームのOTA更新（実装済み・実機確認済み。使い方は§0クイックリファレンス） | [docs/ota.md](docs/ota.md) |
| コマンドラインからのリモート再起動要求（実装済み・実機確認待ち） | [docs/remote_restart.md](docs/remote_restart.md) |
| デバイスの稼働時間・再起動検知の作戦（未着手） | [docs/uptime.md](docs/uptime.md) |
| 複数機の波形を重ねる（姿勢・方位・震度ビュー） | [docs/device_overlay.md](docs/device_overlay.md) |
| 最初の実装計画とユーザーの決定事項 | [plan.md](plan.md) |
| バッチのバイナリ形式 | [docs/wire_format.md](docs/wire_format.md) |
| 決定の経緯・作業ログ索引（**新しいものから読む**） | [docs/progress.md](docs/progress.md) → `docs/log/` |
| 各領域の詳細 | `firmware/` `lambda/` `terraform/` `dashboard/` `tools/` の各 `README.md` |

`memo.md` はユーザーの作業メモ（TODO・思いつき）。要件の出所になることがあるが、
コミット対象ではない。

## 構成（詳細は README.md）

`firmware/`(ESP32) `lambda/`(ingest/detect/api・Python) `terraform/`(AWS)
`dashboard/`(vanilla JS SPA) `tools/`(震度計算・解析・運用CLI・Python)。

## 知っておくべき不変条件

- **送信基盤は [batch-uplink](https://github.com/nna774/batch-uplink) に切り出してある**。
  C++ の `Batch`/`Uploader`/`TimeSync`、Python の `auth`/`devices`/`notify`/`s3util` は
  このレポには**もう無い**。周波数モニタ [Electabuzz](https://github.com/nna774/Electabuzz)
  と共有している。
  - **必ずタグで pin しろ。`#master` や `@master` にするな。** 向こうのために入れた変更が
    こちらの次回ビルドで黙って混入し、「何も変えていないのに再ビルドで壊れる」という
    最悪の壊れ方をする。版は `firmware/platformio.ini` の `lib_deps` と
    `terraform/build_lambda.sh` の `UPLINK_VERSION` の**2箇所。上げるなら揃えろ**。
  - **ワイヤ形式は共有しない。** `Batch` は「ヘッダ領域 + 固定長レコード列 + tail」しか
    知らない。magic・32バイトヘッダ・TLVトレイラーを知っているのは `firmware/lib/NamzWire`
    だけで、ヘッダを書くのは**サンプルを積み終えた後**（`sample_count` が確定するのが
    そこだから）。`firmware/test/run.sh` がバイト等価を守る（golden は切り出し前の実出力）。
  - Lambda の zip は pip を**2回に分けて**呼ぶ。`--platform` は `--only-binary=:all:` を
    要求するが `git+` はソースツリーなので同一呼び出しに混ぜると失敗する。
  - 手元でテストを回すには `.venv/bin/pip install --no-deps "git+...@<tag>"` が要る。
- **計測震度ロジックの単一の真実は `tools/jismo/`**。detect Lambda はこれを共有し、
  ファームのC++実装(`firmware/lib/Shindo`)は `tools/backtest.py` で数値照合してから使う。
  - 照合は**合成波か実イベントの波形で行う**。FFT版は記録全体・FIR版は60秒移動窓なので、
    静穏データで `backtest.py` の diff を見ても意味がない（[docs/intensity_pitfalls.md](docs/intensity_pitfalls.md)）。
  - FFT版は入力を線形デトレンドしてから掛ける。傾斜・熱ドリフトを残すと窓の端が暴れる。
  - **`dashboard/app.js` の `JMA_FIR_TAPS` も同じFIR係数(511tap, fs=100Hz)の第三の写経**
    （ライブ画面「1分」表示のクライアント側概算震度用。`dashboard/README.md`参照）。
    `tools/jismo/fir.py` の `--fs`/`--numtaps` を変えたら、firmwareの `JmaFirTaps.h` と
    合わせてこの配列も手で再生成すること（自動同期は無い）。
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
- **波形を組み立てる時は必ず device_id で絞る**（`lambda/common/store.py`）。raw のキーは
  `raw/.../<device>-<startus>.bin` なので、絞らずに列挙して `sort()` すると**デバイス番号が
  先に効き**、時系列に見えて「1号機の全部→2号機の全部」の順に並ぶ。これを連結すると
  継ぎ目の段差が揺れに見えて震度が跳ねる（実際に踏み、偽の確定報が4件出た）。
  `load_window` / `copy_raw_to_event` は device_id を必須引数にしてある。
- **デバイスの払い出しは `tools/devices.json` が単一の真実**（gitignore対象・鍵を含む）。
  `tools/provision_device.py` が `secrets.h` / `terraform.tfvars` の `device_hmac_secrets` /
  焼く `[env:]` の3本を導出する。**サーバ側を apply してから焼く**（逆順だと 401）。
  - 「単一の真実」は**編集の入口が1つ**という意味で、原本がここにしか無いという意味ではない。
    HMAC鍵の実体はクラウド側に平文で2箇所ある（S3の terraform state / ingest Lambda の
    環境変数 `NAMZ_HMAC_SECRET_<id>`。KMS暗号化していない）。マニフェストを失っても
    `aws lambda get-function-configuration` と `terraform output` から再生成できるので、
    **鍵のローテートや実機の焼き直しは不要**。復元できないのは WiFi パスワードだけ。
    Secrets Manager や KMS へ移す改修をする時は、この復元経路が消えることに注意。
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

**S3オブジェクトに`--cache-control`は付けるな（意図的に付けていない）。** ブラウザの
キャッシュ制御は`terraform/dashboard.tf`の`aws_cloudfront_response_headers_policy`
（`Cache-Control: no-cache`をビューワー応答へ強制的に付与）で行う。CloudFront自体の
エッジキャッシュTTLは`cache_policy_id`（Managed-CachingOptimized、既定1日）任せで、
デプロイのたびのinvalidationで鮮度を保証する。**この2つはレイヤーが違う**——
S3オブジェクト側に`Cache-Control: no-cache`を付けてしまうと、CloudFrontは
Cache PolicyのDefaultTTLより「オリジンが明示した鮮度ヘッダー」を優先するため、
エッジ↔S3間の再検証が毎回発生してしまう（実際に踏んで直した、2026-08-06）。
ブラウザが`app.js`だけ古いキャッシュを使い続けて`index.html`と食い違う元々の
不具合（「新しい列のヘッダーは出るが中身も罫線も途中で切れる」）は、Response
Headers Policy側のno-cacheで別途防げている。

## 開発の約束（グローバル設定に加えて）

- コミットは日本語・意味単位。rebaseせず master を merge。テストは `.venv` で
  `pytest lambda/tests` / `pytest tools/tests`。

## 作業したらログを1本足す

**このレポの進捗は `docs/log/` に日付ファイルを追記する形で記録する。**
既存ファイルを書き換えて履歴を消すな。

1. `docs/log/YYYY-MM-DD-<slug>.md` を新規作成する（1セッション・1トピックで1本）
2. **[docs/progress.md](docs/progress.md) の表に1行追記する**（新しいものが上。1〜3文の要約 + ログへのリンク）
3. 設計判断が変わったなら、**該当する `docs/*.md`（または `CLAUDE.md`）本体も同じコミットで直す。**
   ログは経緯、本体は現在の結論。**両者が食い違ったら本体を正とする**

ログに書くこと: **何を決めたか、なぜそう決めたか、何が覆ったか、次に何が可能になったか。**
作業の実況中継は要らない。**判断とその理由だけ残せ。**
