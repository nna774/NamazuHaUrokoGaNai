# 2026-08-24 CloudFront invalidationが要るのは既存event_idの書き換え時だけと確認し、CLAUDE.md/tools/README.mdの指示を絞った

[浦河沖M6.0の事後解析](2026-08-24-urakawa-oki-m6.0-post-hoc-detection.md)で`promote_event.py`
により新規event_id（`0001-59583090`・`0002-59583090`）を発行した際、CLAUDE.mdの既存の指示
（「`flag_event.py`/`promote_event.py`で書き換えたら自然失効を待たずinvalidationを打て」）に
従って`aws cloudfront create-invalidation --paths '/event*'`を反射的に実行した。ユーザーから
「これって今回も必要なのかな」と聞かれ確認したところ、**今回は不要だった**。

## 確認内容

`terraform/custom_domain.tf`の`aws_cloudfront_cache_policy.api_event`は`id`/`from`/`to`
クエリをキャッシュキーに含む（`query_strings_config.query_strings.items`）。つまり
`/event?id=0001-59583090`と`/event?id=0002-59583090`は別々のキャッシュエントリであり、
**あるevent_idのキャッシュが存在するのは、そのURLが過去に一度でもリクエストされた場合だけ**。

今回の`0001-59583090`/`0002-59583090`は`promote_event.py`で今その場で発行した新規IDで、
`flag_event.py relate`を挟んだ後の検証curlが史上初のリクエストだった。つまり「書き換え前の
古いレスポンス」はそもそも存在しようがなく、無効化してもしなくても初回フェッチの結果は
同じだった。

## 教訓・変更

CloudFront invalidationが実際に意味を持つのは、**既に一度でも取得された(=キャッシュされ得た)
既存event_idの内容を、`flag_event.py`のnote/confirm/unconfirm/relate等で後から書き換えた**
ケースだけ。`promote_event.py`が新規に発行するevent_idの初回フェッチには不要（無効化しても
実害はないが、反射的に打つ判断基準としては不正確だった）。

CLAUDE.md・`tools/README.md`の該当箇所を「既存event_idの書き換え時だけ」と明示する形に
書き換えた。次に`flag_event.py`/`promote_event.py`を使う時、新規発行のみなら invalidation
の要否で迷わなくてよい。
