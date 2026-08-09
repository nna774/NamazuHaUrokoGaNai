# ボタン長押し緊急再起動(v=1726fce)をdevice2へ配信した結果

PR #40（ボタン長押しでの緊急手動再起動）マージ後、実機device2への配信結果を記録する。

## 手順

```bash
tools/publish_ota.sh adxl355
# building env=adxl355 version=1726fce
# uploading to s3://namazu-dashboard-486414336274/ota/adxl355/1726fce.bin

NAMZ_DEVICES_TABLE=namazu-devices python tools/request_ota.py request 2 1726fce --yes
# 更新を許可した: device 2 -> version=1726fce
```

masterはPR #40（このボタン長押し機能）とPR #39（WDT panic仮説の調査ログ、
実装は無し）の両方を含む状態。`git merge origin/master`（ff-only）でPR #40の
作業ブランチをそこまで進めてから公開した。

## 結果

`/devices/2`をポーリングして確認:

| 時刻(目安) | fw_version | boot_epoch_us | uptime_s | pending_ota_version |
|---|---|---|---|---|
| 許可直後 | `ebcdfbf` | (旧) | 1873 | `1726fce` |
| 約1分後 | `1726fce` | (旧のまま) | 1915 | `1726fce`（残存） |
| 約2分後 | `1726fce` | **更新**(差分あり) | 78.5 | `null`（自動クリア） |

- 約1分後の時点では`fw_version`だけ新しくなっていたが`boot_epoch_us`は前回値の
  ままだった。`lambda/common/device_meta.py`の`should_update_boot_epoch()`は
  `BOOT_EPOCH_DRIFT_THRESHOLD_US`(**±2分**)を超えたズレでないと再起動と
  みなさない設計になっており、この時点ではまだ閾値内に収まっていた
  （再起動検知の粗さによる一時的な見かけ、実際には既に新versionで起動済み）
- 約2分後の再確認で`boot_epoch_us`が更新され`uptime_s`が78.5秒まで巻き戻って
  いたことから、実際に再起動していたことを確認した。`pending_ota_version`も
  `ota_watch.reached_target()`により自動クリアされていた（2026-08-06の
  停滞誤検知修正どおりの動作）
- `fw_version=1726fce`の着地・再起動の両方が確認できたので、
  ボタン長押し機能（未検証だった実機動作）はdevice2に配信済みの状態になった。
  **物理ボタンでの実際の長押し操作自体の確認はまだ**（現地作業が必要）

`terraform apply`は今回不要（firmwareのみの変更、Lambda/インフラは無変更）。
