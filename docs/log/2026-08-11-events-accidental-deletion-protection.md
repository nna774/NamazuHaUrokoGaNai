# eventsデータの誤削除防止

## 何を決めたか

`namazu-events`(DynamoDB)とS3の`events/`（唯一の原本・再生成不可）を、
「お前や実行者が直接AWS CLI/コンソールから誤って消すコマンドを叩く」事故から
守るガードを4点追加した。

1. `aws_dynamodb_table.events`に`deletion_protection_enabled = true`
   — `DeleteTable`をAWS側で拒否する。Terraform経由かCLI直叩きかを問わない。
2. 同テーブルに`point_in_time_recovery { enabled = true }`
   — 項目単位の誤delete/誤update（`flag_event.py`の操作ミス等）を35日以内なら
   別テーブルへ復元できる。テーブルごと消えるケースには効かない（1と役割が違う）。
3. `aws_s3_bucket.data`にバケットポリシーで`events/*`への
   `s3:DeleteObject`/`s3:DeleteObjectVersion`をDeny
   — IAM側の許可（誰が消せるか）とは別に、S3はDenyを最優先評価するのでaws CLIの
   誤操作も止まる。
4. 同バケットにversioningを有効化 — 3をすり抜けた場合や誤上書きの保険。

## なぜそう決めたか

DynamoDBの`namazu-events`とS3の`events/`は、CLAUDE.mdに書いてある通り
「単一の真実」で複製元が無い（`raw/`は90日で消える前提の一次データ、`events/`は
そこから確定した最終成果物）。一方でLambda実行ロールのIAMポリシー
(`terraform/iam.tf`)には元々`DeleteItem`/`DeleteObject`が無く、アプリのバグ経由の
削除は既に塞がっていた。残る脅威は「実行者(nana)本人やAI(わがはい)がterraformの
外側で直接AWS CLIを叩いて消す」経路で、これは個人のAWS認証情報がLambdaロールの
制限を受けないため、IAMポリシーだけでは防げない。

検討の過程で当初`terraform lifecycle { prevent_destroy = true }`を候補に挙げたが、
これは**Terraform経由の削除だけ**を止めるものだと気付いて撤回した
（`terraform destroy`は防ぐが`aws dynamodb delete-table`の直叩きには無力）。
AWS API自体を拒否する`deletion_protection_enabled`（DynamoDB）と、
Denyポリシー（S3、Object Lockはバケット作成時にしか付けられず既存バケットに
後付けできないため断念）に差し替えた。

## 副作用として対処したこと

`aws_s3_bucket.data`はversioning導入前提で`raw/`のlifecycle
(`expire-raw`)を書いていなかった。versioningを有効化すると、90日経過後の
expirationは「現行バージョンの削除」に留まり、実体は非current版として残って
課金され続ける（`raw/`が「本当に90日で消える」という既存の前提が壊れる）。
`noncurrent_version_expiration { noncurrent_days = 1 }`を同じruleに足し、
非current化した直後に実体も消えるようにして元の挙動を保った。

## 残っている穴（他セッションのレビューで指摘）

`aws_s3_bucket_policy.data`のDenyは**S3 Lifecycle expirationには効かない**。
Lifecycleによる削除はS3サービス内部の自動処理であり、特定のIAMプリンシパルに
よるAPIリクエストとして発行されるわけではないため、バケットポリシー/IAMポリシーの
評価対象外というのがAWSの既知の挙動。今は`expire-raw`ルールが
`filter { prefix = "raw/" }`で`events/`を対象外にしているから安全だが、将来
このfilterを広げる/typoする変更が入ると、今回追加したDenyポリシーを迂回して
黙って消える。Object Lockなら止められるが、既存バケットには後付けできない
（バケット作成時にしか有効化できない）ため今回は採用せず、`s3.tf`の
`expire-raw`ルール直上にコメントで警告を残すに留めた。緊急度は低い
（今壊れているわけではなく、将来filterを触る時の注意点）。

## 次に何が可能になったか

`terraform plan`で意図通りの差分（DynamoDBテーブル更新2件・S3ポリシー新規・
S3 versioning新規・lifecycle rule更新）のみであることを確認済み。
apply未実施（本番AWSへの変更のため実行者の判断待ち）。
