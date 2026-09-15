# firmwareの実ビルドをCIに乗せた

## 何を決めたか

`.github/workflows/firmware-build.yml`を新設し、`pio run -e <env>`での
実コンパイル可否をPR作成時・master pushで検査するようにした
（[firmware-host-test](2026-09-02-firmware-host-test-ci.md)に続く2段目）。
対象envは本番3系統(`esp32dev`・`adxl355`・`piezo`)と、実センサ無しで結合試験を
再現する`fake-sensor`・`fake-sensor-device2-profile`。`sensortest`系
（実機無しでは価値が薄い）・`provision`系（`secrets_provision.h`が要り
gitignore対象でCIには無い）・`tls-alloc-probe`等の使い捨てprobe/PoC系は対象外にした。

ESP32ツールチェーン一式(数百MB)は`actions/cache`で`~/.platformio`を
`firmware/platformio.ini`のハッシュキーでキャッシュする。手元での実測では
キャッシュ済み状態からのクリーンビルドで1envあたり30〜60秒程度——初回のみ
ダウンロードで数分伸びる想定。

## なぜそう決めたか

envの範囲はユーザーと相談して決めた。「本番3env限定」「+検証用」「全env(provision含む)」
の3択を出し、「本番3env + 検証用env」を選んだ上で、さらに`sensortest`系を除き
`fake-sensor`系だけ残す指示があった——`sensortest`はセンサ検証専用でWiFi/送信を
一切通らないため実機無しの価値が薄く、`fake-sensor`はWiFi接続〜バッチ形成〜送信の
一気通貫を実センサ無しで再現できる点が評価された。

対象5env全てを手元(`.venv/bin/pio`)で実際にビルドし、SUCCESSを確認してから
ワークフローを書いた。

## 何が可能になったか

本番3系統とfake-sensor系のコンパイル・リンク可否がPR時点で機械的に検査される。
`Uploader::hostByName()`スレッドセーフ違反パッチ等、既存envに対する変更が
他envを壊していないかも一度に見える。

## 次に何が可能になるか

`sensortest`・`provision`・probe系のビルド検査は保留。`provision`系を含めるなら
`secrets_provision.h.example`をダミーとしてコピーしてコンパイルのみ確認する方式が
考えられるが、値そのものは実機に焼くものではなくコンパイル通過の確認に留まるため
優先度は低いと判断した。
