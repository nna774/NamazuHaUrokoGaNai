# 2026-09-04 新PC用IAMユーザーA.R.O.N.Aと、namazuに絞ったassume-role運用への切り替え

## 決めたこと

新しいPCからこのAWSアカウント(486414336274)を操作するため、IAMユーザー
`A.R.O.N.A` を作成した。ただし `A.R.O.N.A` 自体には `sts:AssumeRole` しか持たせず、
実際の操作権限は新設したIAMロール `namazu-admin` 側に置く（assume-role方式）。
さらに `namazu-admin` の権限は、**namazuプロジェクトが実際に使うリソースだけに絞った**。

背景: 既存の運用ユーザー `er` は `on-server` グループ(IAMFullAccess込み)+個別ポリシー
+インラインポリシーの組み合わせで、実質ほぼ全リソースへの永続的フルアクセスを持っていた。
このAWSアカウントは namazu 専用ではなく、electabuzz・publikes・saiban-kun・個人サイト
(nna774.net)等、複数の個人プロジェクトが同居している（S3バケット・DynamoDBテーブル・
Lambda関数・CloudFront配信を実際にlistして確認）。真新しいIAMユーザーを作る機会に、
「namazu用の鍵が漏れても他プロジェクトを触れない」形にする方を選んだ。

## namazu-adminロールの最終形

インラインポリシー3本のみ。管理ポリシーは0（試作段階で作った統合カスタムポリシーは
最終的に不要になり削除した）。

- `namazu-scoped-s3` — `namazu-data-486414336274`/`namazu-dashboard-486414336274`の
  2バケットのみ。terraform stateは`nana-terraform-state`内の`namazu.tfstate`キーのみ
  （バケット丸ごとではない）
- `namazu-scoped-compute` — Lambda/DynamoDB/EventBridge(classic events、
  `aws_cloudwatch_event_rule`)は名前が`namazu-*`のものだけ。IAMは`namazu-lambda`
  ロール(Lambda実行ロール)だけ操作可・PassRoleはlambda.amazonaws.comへの委譲に限定
- `namazu-scoped-cdn` — CloudFront/ACMは実在するnamazuのdistribution・cache policy・
  response headers policy・origin access control・証明書のIDに限定。**ただし新規作成系
  アクション(`CreateDistribution`/`RequestCertificate`等)だけはIAMの仕様上リソースを
  指定できず`Resource: "*"`のまま**——ここだけは完全には絞れていない既知のギャップ
  （既存の他プロジェクトのCloudFront/ACMを壊す権限は無いが、新規に何か作る権限は残る）

`er`が持っていたが**namazuのterraformが一切参照していないと確認できたため丸ごと落とした**
もの: Route53系3ポリシー(DNSはCloudflare側管理で外部)、API Gateway管理者(APIは
Lambda Function URL実装でAPI Gatewayを使っていない)、ECS、SSM、CloudFormation full
access及びSAM changeset用カスタムポリシー、ECR、EventBridge**Scheduler**（新サービス。
namazuが使っているのはclassicの`aws_cloudwatch_event_rule`で別物）、Cost Explorer/
Step Functions/Secrets Manager閲覧用インラインポリシー、`umari-notifier-assume`
（別プロジェクト`umari`用）。

MFAはまだ付けていない（今回は見送るとユーザーが判断。`A.R.O.N.A`にMFAデバイス登録と
コンソールパスワード発行が別途必要になるため）。

## 何が可能になったか / 何が変わっていないか

新しいPCから `~/.aws/config` に `[profile namazu-admin]`(role_arn+source_profile)を
設定し、`aws --profile namazu-admin sts get-caller-identity` で
`assumed-role/namazu-admin/...` になることを確認済み。`terraform plan` も権限面では
通ることを確認した（実行自体はterraformバイナリ未導入で失敗、別問題）。

`er`自身の権限構成・ログイン方式は一切変えていない。`er`をassume-role方式に移行する
ことと、`namazu-admin`のCloudFront/ACM作成系アクションの残存ギャップを埋めることは、
どちらも今回のスコープ外として持ち越し。

## 新PCでterraformを動かすために追加で要るもの

`terraform.tfvars`(gitignore対象、秘密値を含む)をコピーすれば`terraform plan`/`apply`
の範囲は足りる——`tools/devices.json`はterraformから直接参照されない
（`provision_device.py`が`devices.json`から`terraform.tfvars`の`device_hmac_secrets`
等を導出する側で、terraformの手前で消費し終わっている）。`devices.json`が要るのは
新PCから`provision_device.py`/`mute_device.py`でデバイス払い出し操作まで行う場合のみ。
ダッシュボードのS3 syncまでやるなら`dashboard/config.js`も別途要る。
`.terraform/`・`terraform/builds/`・`lambda/**/*.zip`はローカル生成物なのでコピー
せず、`terraform init`/`build_lambda.sh`でその都度作り直す。
