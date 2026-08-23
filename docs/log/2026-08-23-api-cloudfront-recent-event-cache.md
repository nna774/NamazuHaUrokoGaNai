# api(/recent, /event)をCloudFrontでキャッシュし、S3 GET課金を頭打ちにする

## 何を決めたか

`~/Downloads/costs.csv`(AWS Cost Explorerから手で絞り込んだS3 API別コスト)を見たところ、
GetObject($3.16、全体$6.24の半分)が支配的に増えていた。**この増加の原因は特定していない。**
分かっているのは、`api` Lambda(Function URL、認証なし公開)が`/recent`・`/event`のたびに
S3へ`get_object`する構造になっており、閲覧回数に比例して増えうる——
[Electabuzz PR#29](https://github.com/nna774/Electabuzz/pull/29)で対処したのと同型の
構造的な穴が存在する、というところまで。実際の増加が本当にこの閲覧経路によるものかは
裏取りできていない(同時期に他の作業も走っていたため)。今回の対応はこの構造上の比例関係
そのものを切り離すもので、効果の実測(コストが実際に下がるか)はapply後の確認事項として
残る。

対応として、既存の`aws_cloudfront_distribution.api`(`terraform/custom_domain.tf`)に
`/recent`・`/event`専用の`ordered_cache_behavior`を追加した(それ以外のパスは既存の
`CachingDisabled`のまま)。

- **`/recent`**: `minutes`/`start`/`device`をキャッシュキーにした固定15秒TTL。新データは
  最速のdevice2(ADXL355)でも15秒バッチ(`firmware/src/config.h`の`kBatchSeconds`)より速くは
  来ないので、鮮度を落とさずに閲覧人数の影響を切り離せる(Electabuzz PR#29と同型。あちらは
  30秒固定、こちらは対象デバイスの最速バッチ間隔に合わせて15秒)。
- **`/event`**: `id`/`from`/`to`をキーに、TTLはLambda側が返す`Cache-Control`ヘッダで
  出し分ける。クラウド確定済み(`meta.json`あり)は波形が書き込み後不変なので1年相当
  (`EVENT_CONFIRMED_CACHE_S`、`lambda/api/handler.py`)。速報のみ(`meta.json`未生成)は
  `max-age=0`で無効化した。

## なぜそう決めたか

`/event`を単純に長TTLにすると、速報段階で開かれたレスポンス(「波形なし」)がキャッシュに
乗ってしまい、直後にクラウド確定しても波形が出るようになるまでTTL分ラグが生じる——地震
直後に見に来た人ほどこの空振りを踏みやすい。確定状態でキャッシュ可否を出し分ける実装を
選んだ(パス単位の固定TTLでは表現できないため、オリジンのCache-Controlヘッダに従う
cache policyにして、Lambda側の分岐に委ねた)。

1年という長さは「note/checked/related_events等を`flag_event.py`/`promote_event.py`で
書き換えても自然失効を待つ運用は成立しない」ことを意味する。そのため書き換え後は
手元で invalidation を打つ運用に倒した(`aws_cloudfront_distribution.api`の
Distribution IDを`terraform output api_distribution_id`として新規に出力した)。
待つのではなく毎回打つ前提にしたのは、「まれに反映が遅れる」より「常に手で1コマンド
打つ」方が運用として迷わないため。

## 何が覆ったか

`terraform/custom_domain.tf`の`aws_cloudfront_distribution.api`のコメントは元々
「ライブデータの陳腐化を避けるため既定はキャッシュ無効」だったが、これは`/recent`・
`/event`にも一律に適用されていた。今回`/recent`・`/event`だけ例外にし、コメントも
「それ以外は既定のCachingDisabledのまま」に直した。

## 次に何が可能になったか

`terraform apply`すれば、閲覧人数がGetObject課金に効かなくなる(1分間に何人`/recent`を
見ていようとオリジンへのアクセスは一定)。過去イベントの再閲覧(SNS等でリンクが拡散する
ケース)もほぼタダになる。適用はまだ行っていない。適用後、実際にGetObjectコストが下がるかを
Cost Explorerで確認すれば、今回の構造が本当に増加の主因だったかどうかの裏取りにもなる。
