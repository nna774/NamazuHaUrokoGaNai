# 2026-08-24 CloudFront invalidationの`--paths`を`/event*`からevent_id単位に絞った

[直前のログ](2026-08-24-cloudfront-invalidation-scope.md)で「invalidationが要るのは既存
event_idの書き換え時だけ」と使うタイミングを絞ったが、実際に打つコマンド自体は
`--paths '/event*'`のままだった。ユーザーから「これって全部のeventキャッシュ飛ぶよね、
もっとpath絞れないか」と聞かれ確認した。

## 確認内容

`terraform/custom_domain.tf`の`aws_cloudfront_cache_policy.api_event`は`id`/`from`/`to`を
query_stringsのwhitelistに登録しているが、`lambda/api/handler.py`の`_event()`は`id`しか
読んでいない（`from`/`to`は未使用）。つまり`/event`のキャッシュエントリは実質
**event_id 1個 = 1エントリ**。

CloudFrontのinvalidationは、キャッシュキーにquery stringを含む配信であれば
`--paths '/event?id=0001-59462454'`のように厳密なquery string付きpathを指定して、その
1エントリだけを狙い撃ちできる。従来の`--paths '/event*'`はワイルドカードなので、
書き換えてもいない他の確定済みイベント（実質1年キャッシュ）まで全部無効化していた。

## 教訓・変更

これは単なるinvalidation APIの課金（無料枠内で実害は薄い）の話ではない。`/event`を
長期キャッシュした目的自体が「閲覧人数比例のS3 GET課金」対策（Electabuzz PR#29と同じ
構造）なので、`/event*`で全消しすると次に誰かが無関係な既存イベントを開いた瞬間
キャッシュミスでLambda→S3を叩かせてしまい、対策前の状態に一時的に戻す。

CLAUDE.md・`tools/README.md`・`terraform/custom_domain.tf`のコメントを、実際に書き換えた
event_idを`/event?id=<eid>`の形で列挙する指示に変更した（複数件なら`--paths`に複数渡す）。
`/event*`のようなワイルドカードは使わない方針に統一した。
