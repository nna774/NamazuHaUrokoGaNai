# `ESP.getMinFreeHeap()`(生涯最小空きヒープ)の送信を実装した

前回のESP32未活用機能の棚卸し（[log/2026-08-30-esp32-hidden-features-survey.md](2026-08-30-esp32-hidden-features-survey.md)）
でユーザーが「記録する価値がありそう」と即決した項目を実装した。

## 何をしたか

`X-Namz-Heap-Free`/`X-Namz-Heap-Maxblock`と全く同じ`extraRequestHeaderNames/Values`の
仕組みに`X-Namz-Heap-Minfree`(`ESP.getMinFreeHeap()`)を追加した。既存の2ヘッダは瞬間値
だが、こちらは起動してから今までの最小値——一時的にしか出ないスローリークの兆候を
瞬間値は見逃しうるが、生涯最小値ならリークがあれば必ず反映される。

- **firmware**: `main.cpp`・`piezo_main.cpp`両方に同じ3点セット（ヘッダ定数・バッファ・
  送信直前のsnprintf）を追加。batch-uplink v2.0.0以降ヘッダ配列はnullptr終端（本数上限
  無し）なので、batch-uplink側の変更は不要だった。
- **lambda**: `metrics.record_heap()`/`latest_heap()`に`heap_minfree`をOptional引数として
  追加。旧ファーム（ヘッダ未送信）との後方互換のため、Noneならそのメトリクスだけ送らない
  ／読まない設計にした——heap_free/maxblockのようにペアで必須にすると、OTA未適用の
  旧ファーム機がまだ動いている間`record_heap`自体が丸ごと壊れる。
- **dashboard**: デバイス詳細ページのヒープ行に「/ 最小XXKB」を追記（値が無ければ省略）。
  CloudWatch深リンクにも`HeapMinFreeBytes`系列を追加。

## 確認したこと

- `pytest lambda/tests`: 168件通過（`test_metrics.py`に新規4件追加）
- firmwareビルド: `esp32dev`・`adxl355`・`piezo`の3env、`test/run.sh`（wire形式golden、
  ヘッダ配列は対象外なので無変更で通って当然だが確認した）
- **実機での配信・CloudWatchへの到達確認はまだ**

## 次にできること

CloudWatchに`HeapMinFreeBytes`が溜まり始めたら、`heap_free`の推移だけでは見えなかった
スローリークが実機で起きていたかどうかを事後に確認できるようになる。
