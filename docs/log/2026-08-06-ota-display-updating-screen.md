# OTA中はTFTの震度画面を「更新中」画面に差し替える

## 何を決めたか

OTA転送中（push/pull共通）は測定タイマーが止まり震度・WiFi・バックログの値が
凍った古い値のまま画面に残り続けていた。これを「更新中で意味を持たない値」と
「今まさに揺れている値」でユーザーが誤認しないよう、OTA中は震度画面ではなく
専用の更新中画面（紫背景 + "OTA UPDATING" + "do not power off"）に丸ごと差し替えた。

## なぜそう決めたか

- `pauseSamplingForOta()`（push型`onStart`／pull型`checkAndPerformPullOta`の両方から
  呼ばれる）が測定タイマーを止めた時点で、`gDispIntensity`等は最後に測定タスクが
  書いた値のまま更新されなくなる。震度画面をそのまま出し続けると「震度が固まって
  見える＝地震計が壊れた」と誤読されうる。
- 日時（`clock`）だけは`loop()`側で毎フレーム計算しているため、OTA中でも表示は
  更新し続けられる。凍結検知（表示が本当に止まっていないか）の役目はこれで
  引き続き果たせるので、更新中画面にも残した。

## 実装

- `main.cpp`に`static volatile bool gOtaInProgress`を追加。書き手は
  `pauseSamplingForOta()`（true化）と`resumeSamplingAfterOtaFailure()`（false化、
  失敗時のみ通る）。Core0(uploaderTask)が書き、Core1(loop)が読む。成功時は
  `ESP.restart()`するのでfalseに戻す必要はない（再起動でゼロクリアされる）。
- リモート再起動要求（`docs/remote_restart.md`）は`pauseSamplingForOta()`を経由
  しない独立の停止シーケンスなので、このフラグには影響しない（更新中画面は
  OTA専用のまま）。
- `Display`に`renderOtaUpdating(clock)`を追加。通常の`render()`が使う
  idle/closing/active(紺/橙/赤)のどれとも被らない紫を背景にして、遠目でも
  「今は震度表示ではない」と判別できるようにした。
- `loop()`は`gOtaInProgress`を見て`render()`と`renderOtaUpdating()`を出し分ける
  （`NAMZ_SENSOR_TEST`ビルドはOTAコード自体が無くフラグは常にfalseなので影響なし）。

## 何が可能になったか

実機での次回OTA確認（push/pull共通、docs/ota.md §6未着手）の際、画面を見れば
「更新中で止まっている」のか「本当に地震計が固まっている」のかを目視で区別できる。
