# device2へOTA配信し、生涯最小空きヒープの実機到達を確認した

PR #183・[前段のLambda/ダッシュボードデプロイ](2026-08-31-heap-minfree-lambda-dashboard-deploy.md)
に続き、実際にファームを配信して`X-Namz-Heap-Minfree`ヘッダがサーバまで届くことを確認した。

## 手順

- `tools/publish_ota.sh adxl355`相当の手順（クリーンなworktree上でビルド、
  `terraform`未初期化だったためS3アップロードのみ手動で`aws s3 cp`）で
  `ota/adxl355/70ae824.bin`を公開
  （`70ae824`は本セッションのdocs専用コミット。firmware内容はPR #183merge後の
  masterと同一で、`main.cpp`/`piezo_main.cpp`に差分なし）
- `tools/request_ota.py request 2 70ae824 --yes`でdevice2に許可
- 約2分後、`/devices/2`で`fw_version=70ae824`・`reset_reason=SW`（正常なOTA再起動）
  ・`pending_ota_version=null`（ingestが自動クリア）を確認
- その後CloudWatchメトリクス集計を待ち、`heap_minfree_bytes=63834`が
  `/devices/2`に現れることを確認（`heap_free_bytes`/`heap_maxblock_bytes`と
  同じ`metrics.latest_heap()`経路）

## 残作業

- device1(IIS3DHHC機)・device3(ピエゾ機)は未配信のまま。必要になったら
  `tools/publish_ota.sh esp32dev` / `piezo`で同様に配信する
