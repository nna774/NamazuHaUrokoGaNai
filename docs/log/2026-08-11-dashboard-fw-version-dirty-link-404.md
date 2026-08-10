# ダッシュボードの版数リンク、-dirty付きだと404だった

## 何が起きたか

デバイス一覧・詳細画面の「版数」列は`firmware/get_fw_version.py`が埋め込んだgit短縮hashを
そのままGitHubのコミットURL（`.../commit/<version>`）にリンクしていた。作業ツリーが汚れた
状態でビルドしたファーム（例: `09d6dc1-dirty`）を焼いた機体では、`-dirty`付きの文字列が
そのままコミットハッシュとしてURLに載り、GitHub側にそんなコミットは存在しないので404に
なっていた。

## 直した内容

`dashboard/app.js`の`fwVersionHtml()`で、リンク先(href)だけ末尾の`-dirty`を削った短縮hashを
使うようにした。表示テキストは`-dirty`付きのまま（未コミット状態で焼いた機体だと分かる
情報を消さないため）。

## 次に可能になったこと

`-dirty`付きの版数を持つ機体でも版数リンクからコミットに飛べる。デプロイはダッシュボードの
S3 sync + CloudFront invalidationが必要（まだ未実施）。
