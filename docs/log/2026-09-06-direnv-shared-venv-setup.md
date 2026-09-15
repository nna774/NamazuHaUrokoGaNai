# direnv導入とworktree間での.venv共有方針

## 決めたこと

- このマシンにdirenvを導入し（`brew install direnv`、`~/.zshrc`に`eval "$(direnv hook zsh)"`）、
  `AWS_PROFILE`を自動で`namazu-admin`にする`.envrc`をリポジトリに置く運用にした。
- `.venv`は本体（`git worktree list`の先頭、`/Users/nana/codes/NamazuHaUrokoGaNai`）に1つだけ置き、
  worktreeからは共有参照する。worktreeごとに複製しない。
- worktree(`<repo>/.claude/worktrees/<name>`、本体にネストされる)側の`.envrc`は最初
  `AWS_PROFILE`/`VIRTUAL_ENV`/`PATH_add`を丸ごと複製していたが、ユーザーの指摘で
  direnv stdlibの`source_up`（親ディレクトリを遡って`.envrc`を探して読む）に切り替えた。
  worktree側は1行(`source_up`)だけになり、本体の`.envrc`を変えれば全worktreeに自動で
  伝播する——値を複製しない分、更新漏れが起きない。

## なぜ

- `.envrc`・`.venv`はどちらも`.gitignore`対象（`.envrc`は#206で追加済み）。つまり
  **`git worktree add`では複製されない**——worktreeは追跡ファイルしかチェックアウトしないため。
- worktreeは作っては消される運用なので、`.venv`（重い・再構築に時間がかかる）を
  worktreeごとに作ると無駄が大きい。`.envrc`は数行なので複製コストは無視できる。
- 一方でCLAUDE.mdは追跡対象なので、この運用ルール自体はCLAUDE.md本体に書けば
  新しいworktreeにも自動的に付いてくる（今回そうした）。

## 覆った点

- 作業中、本体に既にPython 3.9.6の`.venv`（numpy/scipy/pytest等インストール済み、9/4作成）が
  存在するのに気づかず`python3.12 -m venv .venv`を上書き実行し、`pyvenv.cfg`と
  `bin/python3.12`シンボリックリンクが混在する壊れた状態にしてしまった。
  `pyvenv.cfg`を3.9.6の内容に書き戻し、追加された`bin/python3.12`・`lib/python3.12`を
  削除して復旧した。**既存の`.venv`が既にあるかどうかは先に確認すべきだった。**
- ドキュメント更新作業自体でも、`docs/progress.md`とこのログを一度**本体(masterブランチ)の
  作業ツリーに直接書いてしまい**、`git checkout --`で本体を戻してこのworktree側に書き直した。
  `.envrc`/`.venv`が本体に集約される運用と、**git管理下のファイル編集は必ず今の作業ブランチ
  （worktree）側で行う**という原則は別物であり、混同しないこと。

## 次に可能になったこと・残課題

- `namazu-admin`プロファイルでのAWS CLI操作が、cdするだけで（明示的な`--profile`無しで）
  できるようになった。
- 発覚した別問題（未着手）: batch-uplinkパッケージが`Python>=3.12`を要求するため、
  本体の`.venv`（3.9.6）には`pip install git+...batch-uplink`が刺さらず、
  `pytest lambda/tests`が9件collectエラーになる。本体`.venv`をPython 3.12で作り直すか
  検討が必要（既存パッケージの入れ直しが伴うため今回は保留）。
