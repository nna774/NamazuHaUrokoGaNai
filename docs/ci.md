# CI（GitHub Actions）

このリポジトリで動いているワークフローは `doc-link-check`・`firmware-host-test`・
`firmware-build` の3本（`.github/workflows/`）。いずれもPR作成時とmasterへのpushで走る。

**`firmware-host-test`・`firmware-build`は`firmware/**`（と自分自身のワークフロー
ファイル）の変更があった時だけ走る**（`on.pull_request.paths`/`on.push.paths`）。
両方とも見ているのは`firmware/`配下のソース・`platformio.ini`だけなので、docsや
lambda/dashboard/terraform/tools側だけの変更ではスキップする設計。`doc-link-check`は
逆に全ファイル変更で常に走る（doc側の変更こそ検査対象のため）。masterにはbranch
protectionが無く必須チェック指定も無いので、スキップされてもマージがブロックされる
ことはない（`gh api repos/<owner>/<repo>/branches/master/protection`で確認可能）。

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

## firmware-host-test

**何を検査しているか**: `firmware/test/run.sh`（`Batch`/`NamzWire`/`TlsMemPoolCore`の
ホスト側テスト、[firmware/README.md](../firmware/README.md#テストtest)参照）をそのまま走らせる。
実機もPlatformIOもESP32ツールチェーンも不要——`run.sh`が要る`batch-uplink`の実体は、
PlatformIOを介さず`[env:esp32dev]`がpinしているタグを直接`git clone`して用意する
（`firmware/.pio/libdeps/esp32dev/batch-uplink`に展開、run.shの探索パスに合わせている）。
pinバージョンの単一の真実は`firmware/platformio.ini`のまま——ワークフロー側に
バージョン文字列を重複して持たない。

ファーム本体（`main.cpp`・実機向けビルド）自体のコンパイル可否は`firmware-build`が見る。

落ちた場合は`firmware/test/run.sh`を手元でそのまま実行すれば再現する
（`batch-uplink`は`.pio/libdeps`に展開済みが必要。無ければ
`cd firmware && ../.venv/bin/pio run -e esp32dev`で一度ビルドするか、
上記と同じくpinされたタグを直接cloneして`.pio/libdeps/esp32dev/batch-uplink`に置く）。

## firmware-build

**何を検査しているか**: `firmware/platformio.ini`の主要envを実際に`pio run -e <env>`で
ビルドし、コンパイル・リンクが通ることを見る（実機書き込みはしない）。対象は

- 本番3系統: `esp32dev`・`adxl355`・`piezo`
- `fake-sensor`・`fake-sensor-device2-profile`（実センサ無しでWiFi接続〜バッチ送信の
  結合試験を再現する検証用env。秘密不要でそのまま焼ける）

`sensortest`系（WiFi/送信なしのセンサ検証専用、実機無しでは価値が薄い）・
`provision`系（`secrets_provision.h`が要る。gitignore対象でCIには無い）・
`tls-alloc-probe`/`panic-test`/`psram-probe`/`pool-probe`系・`pioarduino-fake-sensor`
（いずれも使い捨てのPoC/実機計測用）は対象外。

ESP32ツールチェーン/フレームワーク一式（数百MB）は`actions/cache`で`~/.platformio`を
`firmware/platformio.ini`のハッシュキーでキャッシュしている。`platform`バージョンや
`lib_deps`を変える編集をすると初回のみキャッシュミスして数分伸びる（手元の実測では
キャッシュ済み状態からのクリーンビルドで1env あたり30〜60秒程度）。PlatformIO自体は
手元(`.venv`)と揃えたバージョンで`.github/workflows/firmware-build.yml`内にpinしてある。

落ちた場合は該当envを手元でそのままビルドすれば再現する: `cd firmware && ../.venv/bin/pio run -e <env>`。
