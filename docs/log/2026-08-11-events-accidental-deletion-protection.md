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
(`expire-raw`)を書いていなかった。versioningを有効化すると、expiration経過後の
削除は「現行バージョンの削除（delete markerが乗る）」に留まり、実体は非current版
として残って課金され続ける（`raw/`が「本当に消える」という既存の前提が壊れる）。
`noncurrent_version_expiration`を同じruleに足して対処したが、日数は下記の
「残っている穴」の議論を経て30に決めた（経緯は次節）。

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

## raw_retention_daysを90→60に短縮し、その分をnoncurrent_daysに回した

上記の「filterが将来壊れたら気付くまでの猶予」を実際に確保する手として、
`noncurrent_version_expiration`の日数をversioning導入直後の暫定値(1日)から
30日に伸ばした。実体（旧current version）はexpiration後も30日分は物理的に
残るので、事故発生から気付いて対処するまでの猶予がそのまま30日になる。

その代わり`raw_retention_days`を90→60に短縮し、実体が存在する期間の合計
（60+30=90日）をversioning導入前の90日運用とほぼ同じストレージ量に揃えた
（アプリから見える寿命だけが90日→60日に短縮される。delete markerが乗った
時点で通常のGetObjectには404になるため）。

90日という数字自体を洗い直した。`git log`で確認したところ
`raw_retention_days=90`のデフォルトと、`docs/design.md`の
「閾値・継続秒数は生データ90日分でバックテストしてチューニングする」という
記述は**同じコミット（2026-07-12）で同時に書かれていた**——データに基づく
要件から逆算した数字ではなく、90という数字を決めてから後付けで理由を添えた
順序に見える。かつ**terraformを初めて導入したのがその2026-07-12で、今日
（2026-08-11）でまだ丸30日しか経っていない**。90日ぶんの過去rawというものが
そもそも存在しないため、「90日分バックテスト」も「90日ギリギリの事後解析」も
まだ一度も実行されていない（実際に見つかった事後解析の実例は2件とも発生
当日〜翌日に行われたもので、90日近くまで遡った実例は無かった）。以上から
「最初に適当に決めた数字」と判断し、実測データの裏付けが無いまま90を
維持する理由は薄いと結論した。`docs/design.md`のバックテストの記述からも
「90日分」という具体的な日数は外し、この決定へのリンクを残した。

## 次に何が可能になったか

`terraform plan`で意図通りの差分（DynamoDBテーブル更新・S3ポリシー新規・
S3 versioning新規・lifecycle rule更新）のみであることを確認済み。
apply未実施（本番AWSへの変更のため実行者の判断待ち）。`raw_retention_days`は
`terraform.tfvars`（gitignore対象）側の明示的な上書きが実際に効く値なので、
`variables.tf`のdefault変更とは別に、そちらも60へ手動で書き換える必要がある。
