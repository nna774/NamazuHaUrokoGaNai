# firmware-build/firmware-host-testをdocのみの変更でスキップする

## 何を決めたか

`firmware-build`・`firmware-host-test`の2ワークフローに`on.pull_request.paths`/
`on.push.paths`を追加し、`firmware/**`（と自分自身のワークフローファイル）が
変更された時だけ走るようにした。`doc-link-check`は対象外（doc側の変更こそ検査対象
のため、常に全変更で走らせたまま）。

## なぜそう決めたか

ドキュメントのみの変更（`docs/`配下や各`README.md`など）でも毎回ESP32ツールチェーン
込みのフルビルドが走っており、無駄が大きかった。

線引きは「docファイルを列挙してignoreする」ではなく「`firmware/**`が変更された時だけ
走らせる」(allowlist)方式を採用した。理由:

- `firmware-build`/`firmware-host-test`が実際に見ているのは`firmware/`配下の
  ソースと`platformio.ini`だけで、`lambda/`・`dashboard/`・`terraform/`・`tools/`・
  ルートのdocファイルはどれも無関係。「firmwareに関係ないから走らない」の方が
  「docだから走らない」より本質的な線引きになる。
- ignoreリスト方式だと`docs/img/`のような新しいファイル形式が増えるたびに
  パターンを追記する必要があるが、allowlist方式なら`firmware/**`だけ見ていれば
  よく保守が要らない。

ワークフローファイル自身も`paths`に含めた。ワークフロー定義を変更した時にそれが
検証されないと、壊れたCI設定に気づけないため。

merge前に、masterにbranch protectionが設定されているか(`gh api
repos/<owner>/<repo>/branches/master/protection`)を確認し、404（未設定）と確認
した。必須チェック指定が無いため、path filterでスキップされてもPRマージが
ブロックされる心配は無い。

## 次に何が可能になったか

docs配下のみの変更のPRでは、`firmware-build`・`firmware-host-test`の2本が
スキップされ、`doc-link-check`のみが走るようになった。
