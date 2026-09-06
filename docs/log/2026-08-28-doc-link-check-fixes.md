# doc-link-checkでMarkdownの壊れリンク・到達不能READMEを直した

## きっかけ

「起点ドキュメントから全部のdocsに辿り着けるかチェックするスクリプトが欲しい」という
相談から、その場で試作した。試したところ本リポジトリ固有の知識が無い汎用ツールだと
分かったので、[nna774/doc-link-check](https://github.com/nna774/doc-link-check)として
Go製CLIに書き直し独立リポジトリへ切り出した（public, MIT）。壊れリンク検出自体は
markdown-link-check等の既製ツールで足りるが、「リンクは生きているが起点から辿り着けない
孤立ファイル」の検出は既製ツールに見当たらなかったため、その部分だけを担う。

## 見つけたもの・直したもの

`doc-link-check --root CLAUDE.md --root AGENTS.md --root README.md`で本リポジトリを
検査し、以下を直した。

**壊れリンク8件**（ディレクトリ移動・改名の残骸で相対パスが古いまま）:

- `docs/design.md` → `2026-08-08-heap-telemetry.md`（`docs/log/`配下に移動済みだった）
- `docs/log/2026-08-19-other-sensors-more-ideas.md` → `piezo.md`・`geophone.md`
  （`docs/log/`から見た相対パスのまま、`../`が抜けていた）
- `docs/log/2026-08-08-emergency-reboot-button-field-fixes.md` →
  `log/2026-08-08-emergency-reboot-button.md`（同一ディレクトリ内なのに`log/`が
  二重に付いていた）
- `docs/log/2026-08-06-ota-pull-strategy-design.md`・
  `2026-08-06-remote-restart-implementation.md`・`2026-08-06-remote-restart-design.md`
  （2箇所） → `remote_restart.md`・`ota.md`（同様に`../`が抜けていた）

**到達不能なREADME 3件**（存在してリンクも壊れていないが、起点から辿る経路が無かった）:

- `firmware/README.md`・`lambda/README.md`: `CLAUDE.md`の「各領域の詳細」行が
  `firmware/` `lambda/` ... の各`README.md`とバッククォート表記のみで、実リンクに
  なっていなかった。5つとも実リンクに直した（`terraform/README.md`・
  `dashboard/README.md`・`tools/README.md`は他経路で既に到達可能だった）。
- `tools/testdata/README.md`: `tools/README.md`のどこからも触れられていなかった。
  jismoパッケージ節の直後に一文リンクを追加した。

なお`docs/remote_restart.md`等が`memo.md`（gitignore対象・コミット対象外の作業メモ）を
指しているのは意図通りで壊れていない——ツールをこのリポジトリのworktree（untrackedな
`memo.md`を持たない）から実行すると誤検知するが、これはworktreeが未追跡ファイルを
共有しない仕様によるもので、本チェックアウトでは問題ない。

## 対応

上記11件をまとめて修正。実装・設計そのものの変更は無し、リンク切れの解消のみ。
