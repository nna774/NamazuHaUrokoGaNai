# batch-uplinkのpinをv2.12.0→v2.13.0へ更新した（2026-08-11）

## 背景

`uploaderTask`の吸い出し/送信タスク分割（[NamazuHaUrokoGaNai PR #79](https://github.com/nna774/NamazuHaUrokoGaNai/pull/79)）に対応する
`Uploader`のmutex化・ram_満杯時の自発`flushToSpill()`・関連デバッグログ
（[batch-uplink PR #22](https://github.com/nna774/batch-uplink/pull/22)）をマージし、`v2.13.0`をタグ付けした。
経緯は[log/2026-08-11-uploader-task-split-design.md](2026-08-11-uploader-task-split-design.md)・
[log/2026-08-11-uploader-starvation-under-sustained-send-failure.md](2026-08-11-uploader-starvation-under-sustained-send-failure.md)参照。

`firmware/platformio.ini`のlib_depsと`terraform/build_lambda.sh`のUPLINK_VERSIONを
両方`v2.13.0`へ揃えた。

## 確認したこと

- `pio run -e esp32dev -e adxl355 -e fake-sensor`（実タグ経由、ローカルpath指定ではない）成功
- `firmware/test/run.sh`（ワイヤ形式golden test）all ok
- esp32dev機(fake-sensor env)実機での動作確認は本PRの一連の開発中に既に実施済み
  （`docs/log/2026-08-11-uploader-starvation-under-sustained-send-failure.md`）

## device2(ADXL355機)での見込み

まだ実機(adxl355)には焼いていないが、今回の2つの修正はどちらも**バッチ周期に
依存しない反応速度**なので、device2（`kBatchSeconds=15`・`kMaxRamBatches=3`、
esp32dev機の`kBatchSeconds=30`・`kMaxRamBatches=2`より周期が短くRAM上限が
1本多い）でも同様に効くと予想している:

- タスク分割自体はCore0上のFreeRTOSタスク構成の話で、バッチ周期に依存しない
- `pump()`の`ram_.size() >= maxRam_`チェックは呼び出し周期(~50ms)ベースで、
  バッチ周期(15秒)に対して依然として約300倍速い(esp32dev機の30秒に対する
  約600倍より比率は小さいが、桁は変わらない)

むしろdevice2は元々[log/2026-08-11-device2-upgrade-concern.md](2026-08-11-device2-upgrade-concern.md)で
「バッチ周期15秒がDNS詰まり等のブロック時間(14〜20秒)と同程度以下のため、
プール枯渇(`newBatch stuck`)が1号機より高頻度に出る可能性がある」と懸念されて
いた機体で、**この一連の修正が直そうとしている問題そのものに元々より近い**。
そのぶん恩恵も大きいはずだが、裏を返せば見えていなかった別の限界を掘り出す
可能性もある——実機確認するまでは推測の域を出ない。

device2は`docs/log/2026-08-11-device2-upgrade-concern.md`の時点で「稼働中版数
`ba23fb3`(TlsMemPool以降の全変更より前)」のまま投入保留になっており、この
pinもまだ含め投入していない。実機投入は別途判断する。

## 次に何が可能になったか

`NamazuHaUrokoGaNai`側([PR #79](https://github.com/nna774/NamazuHaUrokoGaNai/pull/79))にこのpin更新コミットを足してマージへ進められる。
