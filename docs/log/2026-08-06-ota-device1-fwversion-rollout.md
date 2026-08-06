# fw_version報告つきファームをdevice1にもOTA配信する

## 何を決めたか

`fw_version`報告機能([PR#15](https://github.com/nna774/NamazuHaUrokoGaNai/pull/15))は
device2（adxl355 env）でのみ実機確認・配信済みで、device1（esp32dev env）向けの
`ota/esp32dev/c64f379.bin`が未公開だった。device1はpush/pull型OTAとも
[事前にNVS化・実機確認済み](2026-08-06-ota-device1-prep.md)なので、同じ版(c64f379)を
esp32dev envでビルドし直して公開し、`tools/request_ota.py request 1 c64f379`で
配信許可を出した。

## なぜそう決めたか

device1・device2は同じfirmwareソース（envが違うだけ）を使っているが、OTA配布物は
env別にビルド・公開する運用（`tools/publish_ota.sh <env>`）なので、device2への配信だけ
では自動的にdevice1へは伝播しない。両機とも同じ版数で揃えておかないと、ダッシュボードの
「版数」列を見た時にdevice1だけ空欄のままで「壊れているのか未確認なのか」の区別が
つかない状態が続く。

## 何が覆ったか

なし。

## 次に何が可能になったか

- device1の`/devices/1`の`fw_version`が`c64f379`で着地し、`pending_ota_version`と
  一致することを確認した（実行から約3〜5分後、要求後の最初のバッチ送信サイクルで反映。
  `batches_total`は67749→67759まで進み、欠測通知は鳴らなかった）。
- 両機とも同じ版数(c64f379)で揃い、ダッシュボードの版数・OTA列がdevice1・device2の
  両方で実データを表示するようになった。
