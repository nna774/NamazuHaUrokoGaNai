# firmware host testをCIに乗せた

## 何を決めたか

`.github/workflows/firmware-host-test.yml`を新設し、`firmware/test/run.sh`
（`Batch`/`NamzWire`/`TlsMemPoolCore`のホスト側テスト）をPR作成時・master pushで
自動実行するようにした。ファーム本体（`main.cpp`、実機向けビルド）のコンパイル可否
チェックは今回は見送り、host testだけをスコープにした。

## なぜそう決めたか

「CIでファームがビルドできるかチェックしてもいいか」という提案がきっかけだったが、
実機向けビルドはESP32ツールチェーン一式のダウンロードが要り実行時間の桁が変わる。
まず安く効くhost testだけを先に乗せる方針にした。

host testは`batch-uplink`（外部ライブラリ、`Batch.cpp`等）の実体を要求するが、
PlatformIOを介して取得すると同じくESP32プラットフォームパッケージの解決が走り
toolchainダウンロードを避けられない。そこでPlatformIOを完全に迂回し、
`[env:esp32dev]`がpinしているタグをそのまま`git clone`して
`firmware/.pio/libdeps/esp32dev/batch-uplink`に展開する方式にした
（`run.sh`の`find "$DEPS" -maxdepth 2 -type d -name batch-uplink`がそのまま拾える
配置）。バージョン文字列はワークフロー側に埋め込まず`firmware/platformio.ini`の
`[env:esp32dev]`セクションから`awk`+`grep`で読む——CLAUDE.mdの「pinは2箇所（platformio.ini
とbuild_lambda.sh）だけ、揃えて上げろ」を壊さないため、3箇所目を増やさない設計にした。

## 何が可能になったか

`Batch`/`NamzWire`のバイト等価性（`test_batch_bytes.cpp`のgolden）と
`TlsMemPoolCore`の不変条件が、手元での`firmware/test/run.sh`実行を忘れても
PRの時点で機械的に検査されるようになった。ローカルで一度動作確認済み
（全ケースPASS）。

## 次に何が可能になるか

実機向けビルド（`pio run -e esp32dev`等）のCI化は保留。要る場面が増えたら
`actions/cache`で`~/.platformio`をキャッシュする方向で検討する
（`docs/ci.md`のfirmware-host-testの節に注記済み）。
