# doc-link-checkをCIワークフローとして常設した

## 何を決めたか

前の作業（[2026-08-28-doc-link-check-fixes.md](2026-08-28-doc-link-check-fixes.md)）で
壊れリンク・到達不能READMEを手動で見つけて直したが、再発を防ぐには継続的なチェックが
要ると判断した。

pre-commit hookとGitHub Actionsを比較検討し、Actionsを選んだ。hookは`.git/hooks`が
cloneに乗らず`core.hooksPath`の設定漏れで静かに効かなくなる（worktreeを切るたびに
再設定が要る）のに対し、Actionsは環境非依存で確実に走る。本リポジトリにCIは
今まで一切無かった（`pytest`もデプロイも手動運用）が、このチェックのために初めて
`.github/workflows/`を作った。

`memo.md`（gitignore対象・追跡外）へのリンクは、CIのフレッシュcloneでは
未追跡ファイルが存在せず毎回誤検知するため、doc-link-check側に
`--ignore-missing`オプションを新設して対応した（`nna774/doc-link-check` v1.1.0）。

## 何が可能になったか

- PR作成時・master push時に`doc-link-check`が自動で走り、ドキュメントのリンク切れ・
  孤立ファイルをCIで検知できるようになった
- 落ちた時の読み方・直し方は[docs/ci.md](../ci.md)にまとめ、`CLAUDE.md`の
  「ドキュメントの歩き方」表から辿れるようにした（次に落ちた時、この場しのぎで
  出力を都度解読しなくて済む）
- ツール本体（`nna774/doc-link-check`）の版はタグpin（`@latest`だと更新のたびに
  CIの挙動が黙って変わりうるため。`.github/workflows/doc-link-check.yml`内、
  現在`v1.1.1`。`v1.1.1`はコードスパン内のリンク例（`` `[text](path.md)` ``の
  ような説明文）を実リンクと誤検出する不具合の修正）
