# 2026-09-27 UPSバッテリー電圧のADC計測・送信経路を設計・実装した

## 何をしたか

docs/ups.md §4のCR/OK LED読み(プルアップ電圧・オープンドレインかどうか未確定のまま
2週間近く止まっていた)に代わる案として、LFUPSMAのB+/B-パッドから分圧でESP32の
ADCへ実電圧を取り込む設計を検討し、配線図・firmware・クラウド側まで一式実装した。
実機の分圧回路はまだ組んでいない(設計・コードのみ、opt-inビルドフラグで既定無効)。

## 決めたこと

- **配線**: 100kΩ+100kΩの2:1分圧+0.1µFコンデンサ→GPIO39(ADC1_CH3)。ADC2はWiFi使用中
  使えないためADC1系統必須。GPIO37/38は個体により未搭載の疑いがあるため避け、
  GPIO34/35はTTGO T-Display内蔵回路・右ボタンの占有ぶんとして空けておく判断。
  図は[docs/img/ups-battery-adc-wiring.svg](img/ups-battery-adc-wiring.svg)。
- **firmware**: `firmware/lib/Battery/Battery.h`(新規、`analogReadMilliVolts()`64サンプル
  平均+分圧比)、`config.h`に`kPinBatteryAdc`/`kBatteryDividerRatio`、ビルドフラグ
  `NAMZ_BATTERY_ADC`(既定無効、`flags_from_env.py`のトグル経由)。有効時のみ
  `X-Namz-Battery-Mv`ヘッダを既存のheap/uptime等と同じ枠組みで毎バッチ乗せる。
  `NAMZ_BATTERY_ADC=1 pio run -e adxl355`でビルド成功確認済み(実機未配線)。
- **クラウド側の保存先を2転three転した**:
  1. 最初はheap/backlogと同じCloudWatchカスタムメトリクスとして実装し、送信頻度が
     Lambda実行時間コストに響くと考えて5分間引きを入れた。
  2. ユーザー指摘で、この規模(3台・15〜30秒毎)のLambda実行時間コストは無料枠に対し
     誤差レベルで、そもそも最適化する意味が無い対象だったと判明。
  3. CloudWatchの実際の課金構造は「メトリクス種別×次元」ごとの**送信頻度非依存の
     固定費**(月$0.30程度/種別)だと確認。間引きは効かない場所を最適化していた。
  4. 温度トレンド(`lambda/common/device_temp.py`)が既に同じ問題(低頻度・書き込み側で
     頻度が天井打ちする時系列を、公開読み取りAPIの閲覧回数に課金が比例しない形で
     持ちたい)を解決済みの前例だと気づき、CloudWatch実装を全撤回してDynamoDB
     オンデマンドテーブル方式に作り直した。間引きも不要になった(書き込み従量が
     この頻度なら無視できるため)。
- **最終形**: `lambda/common/battery.py`(device_temp.pyと同型)、DynamoDBテーブル
  `namazu-device-battery`(pk=device_id, sk=batch_start_us, TTL90日、PAY_PER_REQUEST)、
  ingest handlerが毎バッチ`battery.record()`、api Lambdaに`/devices/<id>/battery?hours=<n>`、
  ダッシュボードのデバイス詳細ページに電圧トレンドの折れ線チャート(temp表示と並列、
  対応機体か否かはtempと違い事前フラグが無いため0件レスポンスで判定しセクションごと
  隠す)。

## 次に何が可能になったか

実機で分圧回路を組んでB+/B-へ接続すれば、`NAMZ_BATTERY_ADC=1`でビルドし直すだけで
充放電カーブがダッシュボードに出るところまでクラウド側は準備済み。残っているのは
実機較正(テスターとADC読みの突き合わせ、`kBatteryDividerRatio`の実測値への置き換え)
と`terraform apply`でのテーブル作成のみ。

## 覆ったこと

- CloudWatchカスタムメトリクスでの実装(`metrics.record_battery`/`latest_battery`)は
  上記の理由で完全に撤回し、コードは残していない。「送信頻度を間引けばコストが
  下がる」という前提自体が、この課金構造には当てはまらなかった。
