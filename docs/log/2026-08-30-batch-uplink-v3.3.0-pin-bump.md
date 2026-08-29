# 2026-08-30 batch-uplink v3.3.0へのpin更新

[2026-08-29-device2-wdt-timeout-budget-implementation.md](2026-08-29-device2-wdt-timeout-budget-implementation.md)
で実装した`batch-uplink` PR #27がマージされたため、`v3.3.0`をタグ付けし
（`Uploader`のTCP接続・TLSハンドシェイク・レスポンスヘッダ読み取りタイムアウトを
3000ms/3000ms/3000msへ縮め最悪合計19秒→12秒に短縮、3値をコンストラクタ引数化）、
`firmware/platformio.ini`(`[env:esp32dev]`・`[env:piezo]`の2箇所)と
`terraform/build_lambda.sh`の`UPLINK_VERSION`を`v3.2.0`→`v3.3.0`へ揃えた
（CLAUDE.mdの不変条件「firmware側・terraform側の2箇所、上げるなら揃えろ」通り）。

`Uploader`のコンストラクタに新しい末尾引数(`connectTimeoutMs`等)が増えたが
既存呼び出し側(`firmware/src/main.cpp`)は省略しているため既定値(3000/3000/3000)
がそのまま効く——シグネチャ変更後もコード変更は不要だった。

## 確認したこと

- `pio run -e esp32dev -e adxl355`のフルビルドが通ることを確認（実機フラッシュは未実施）
- `PYTHON=.venv/bin/python terraform/build_lambda.sh`で全Lambda(ingest/api/watchdog/detect)の
  zip生成が`git+https://github.com/nna774/batch-uplink@v3.3.0`から成功することを確認
  （`terraform apply`は未実施——ビルド成果物`terraform/builds/`はコミット対象外なので生成後に削除した）

## 次に何が可能になったか

- `terraform apply`でLambdaへ配信、`pio run -t upload`でdevice1/device2へOTA配信すれば
  実機に今回のWDT対処が反映される（このセッションでは未実施）
- 実機確認後、TASK_WDTでのパニック再起動が実際に収まったか（今度はパニックせず
  バックオフに落ちて`false`を返すログが出るか）を確認する必要がある
