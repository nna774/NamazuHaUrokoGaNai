# ボタン長押しでの緊急手動再起動を実装した

PR #39（未マージ・draft）でdevice1の再起動をWDT panic仮説（`uploaderTask`のtask
watchdogが`WiFiClientSecure`のTLSハンドシェイクタイムアウトより先に発火し、詰まると
強制パニック再起動する）で調査していた。仮説の裏付けはまだ実機で取れていないが、
「家庭内ネット不調が引き金になり得る」「リモート再起動は通信不調そのものが原因だと
届かない」という点は動かないので、**通信に頼らず現地のボタンだけで安全に再起動できる
手段**を先に実装することにした。`docs/design.md`§送信の信頼性の未定事項に
「物理ボタン長押しでの手動`flushToSpill()`」として既に構想があったので、その実装。

## 設計

TTGO T-Displayの左ボタン(GPIO0、`kPinButtonFlip`)は元々「押すと画面反転」の単機能
だった。同じボタンに以下を足した（新規ボタンの追加は無し、配線変更も不要）:

- **短押し**（`kRebootHoldConfirmMs`=2秒未満で離す）: 従来どおり画面反転のみ
- **2秒以上**押し続ける: 確認画面（黄背景「HOLD TO REBOOT」+ カウントダウン）に
  切り替え、**その時点で**`uploaderTask`(Core0)へキューの先回り退避
  (`flushToSpill()`)を指示する
- **5秒**（`kRebootHoldTriggerMs`）まで押し続ける: 実際の再起動を指示。画面は
  「REBOOTING」に変わる
- confirm閾値未満で離せば何もせず通常表示に戻る（キャンセル）。先回り退避が
  発生していても実害は無い（`flushToSpill()`はRAMキューが空ならほぼ無償で、
  退避済みでも通常のバックフィルで送信が続くだけ）

2段階にしたのは誤操作防止のため。「確認画面に入った時点で退避を始める」のは、
ユーザーが確認画面を見てから実際に再起動を確定するまでの数秒を、退避猶予として
使えるようにする狙い（読んで判断する時間ぶん、退避が先に進んでいてほしい）。

再起動の実行はリモート再起動（`docs/remote_restart.md`）と同じ
`uploaderTask`内の`restartRequested`の仕組みに合流させた。新しいvolatileフラグ
2つ（`gManualRebootArmed`/`gManualRebootConfirmed`、`loop()`/Core1が書き
`uploaderTask`/Core0が読む。既存の`gOtaInProgress`の逆方向）を立てるだけで、
Uploaderの「2xxが返るまで捨てない」不変条件やtask watchdog対策
（再起動直前の`esp_task_wdt_reset()`）をそのまま流用できる。`gUploader`自体は
Core0(uploaderTask)からしか触らない設計を崩していない——`loop()`側は
フラグを立てるだけで、`flushToSpill()`の実際の呼び出しは全てCore0側。

ボタン読み取り(`loop()`)と送信タスク(`uploaderTask`)は別コアなので、
2026-08-07の実測（「`uploaderTask`だけが詰まり`loop()`は生きている」）どおり、
Core0が長時間ブロックしていてもボタンでの再起動要求自体は効く。ただし
`gBatchQueue`（深さ4の浅いキュー、drop-oldest）より前のデータは既に失われた
後なので、早めに気づいて押すことが前提になる点は変わらない
（`docs/design.md`§送信の信頼性を参照）。

`NAMZ_SENSOR_TEST`ビルド（WiFi/Uploader無し）は対象外とし、元の単純な
エッジトリガー方式（押した瞬間に画面反転）のまま変更していない。

## 実装

- `firmware/src/config.h`: `kRebootHoldConfirmMs`(2000)・`kRebootHoldTriggerMs`(5000)
- `firmware/lib/Display/Display.h`/`.cpp`: `renderRebootHold()`を追加
  （`renderOtaUpdating()`と同型、黄背景）
- `firmware/src/main.cpp`:
  - `gManualRebootArmed`/`gManualRebootConfirmed`（volatile bool）
  - `loop()`: ボタンの押下エッジ〜保持時間を`pressStartMs`/`rebootArmed`
    （ローカル変数）で追跡し、閾値到達でグローバルフラグを立てる。短押しの
    flipは離した時点(release)に判定するよう変更した（press edgeでは
    短押しか長押しかまだ分からないため）。体感上の遅延は無視できる
  - `uploaderTask`: `gManualRebootArmed`/`gManualRebootConfirmed`を見て
    既存の`restartRequested`フローに合流

## 動作確認

- `pio run -e esp32dev` / `pio run -e adxl355` 両方成功
- `firmware/test/run.sh`（wire形式のバイト等価テスト、無関係だが念のため）成功
- **実機での動作確認はまだ**（ボタン長押し〜確認画面〜実際の再起動、TFT表示の
  見た目を含む）
