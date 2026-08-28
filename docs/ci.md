# CI（GitHub Actions）

このリポジトリで動いているワークフローは現状 `doc-link-check` 1本のみ
（`.github/workflows/doc-link-check.yml`）。PR作成時とmasterへのpushで走る。

## doc-link-check

**何を検査しているか**: `CLAUDE.md`・`AGENTS.md`・`README.md`を起点に
Markdownの`[text](path.md)`リンクを再帰的に辿り、

1. リポジトリ内の`.md`のうち**どこからも辿り着けない孤立ファイル**
2. **リンク切れ**（存在しないファイルへのリンク）

を検出する。ツール本体は別リポジトリ
[nna774/doc-link-check](https://github.com/nna774/doc-link-check)（Go製・汎用、
このリポジトリ固有の知識は持たない）。**必ずタグでpinする**
（`.github/workflows/doc-link-check.yml`内。`@latest`だとツール更新のたびに
CIの挙動が黙って変わりうるため）。

## 落ちた時の直し方

出力は2種類のセクションに分かれる。

- **`# broken links`**: `src -> dst (missing)`の形で出る。`dst`が実際のファイル位置と
  ずれている（ディレクトリ移動・改名の残骸が典型）。`src`ファイルを開いて、`dst`への
  相対パスを実際の位置に合わせて直す。
- **`# unreachable .md files`**: そのファイルへ、起点(`CLAUDE.md`/`AGENTS.md`/
  `README.md`)から辿れる実リンクが1本も無い。索引になっているファイル
  （`CLAUDE.md`の「ドキュメントの歩き方」表、`docs/progress.md`、各ディレクトリの
  `README.md`など）から、そのファイルへの`[text](path.md)`リンクを1本足す。

**`memo.md`（gitignore対象・追跡外）へのリンクは`--ignore-missing memo.md`で
最初から無視する設定にしてある**——CIはフレッシュcloneのため未追跡ファイルが
存在せず、無視しないと毎回誤検知する。同様に追跡外のファイルを新たにdocsから
リンクする場合は、ワークフローの`--ignore-missing`にも追記すること。

手元で再現するには:

```bash
go install github.com/nna774/doc-link-check@v1.1.1   # ワークフローと同じ版
cd /path/to/NamazuHaUrokoGaNai
doc-link-check --root CLAUDE.md --root AGENTS.md --root README.md --ignore-missing memo.md
```

（経緯: [docs/log/2026-08-28-doc-link-check-fixes.md](log/2026-08-28-doc-link-check-fixes.md)）
