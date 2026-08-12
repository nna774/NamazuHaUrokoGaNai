# dashboard: 非校正センサ(ピエゾ等)でgal前提の表示を出さないようにする

## 何を決めたか

device3(ピエゾ実験機)をライブ画面で選ぶと、センサ生値をgal相当として扱う
クライアント側概算震度（`computeIntensity`、`JMA_FIR_TAPS`）が計算され、
実際には物理的な意味を持たない震度バッジが出てしまっていた。縦軸の
レンジ選択肢（`±100 gal`等）とヘルプ文言も同様に「gal」と表示し続けていた。

detect Lambdaの非校正センサガード（`wire.is_calibrated()`、`sensor_type`が
`128〜249`なら震度計算をスキップ）と同じ判定をdashboardにも持たせるため、
`lambda/api/handler.py`の`_device_view()`に`calibrated`真偽値を追加した
（`wire.is_calibrated()`を再利用。`sensor_type`未記録時は`hasTemp`と同じ
「見えないよりまし」でTrue扱い）。`dashboard/app.js`はこれを見て:

- `updateLiveIntensity()`: `calibrated=false`なら計算自体をスキップし、
  「非校正センサのため計算しません」と表示する。
- `drawWaveform()`のレンジ外警告・`縦軸:`の`<select>`の選択肢・
  ヘルプ文言（`#live-axes-help`）: `calibrated=false`の間は「gal」を落とし、
  センサ生値であることが分かる文言に差し替える。

デバイス選択のたびに`fillLiveDevices()`が`/devices`を引き直すので、
機を切り替えれば表示も追従する。

## なぜ

`docs/other-sensors.md`で当初から「dashboardの表示も、gal目盛りをそのまま
出すと嘘になるので配慮が要る」と課題として挙げていた箇所（[docs/piezo.md §7](../piezo.md#7-phase1クラウド統合の設計方針未実装)
の実装時点では「`dashboard/app.js`は無改修」で済ませていたが、それは波形の
描画自体（axesのpadding）の話で、gal前提のロジック側は手つかずのままだった）。

判定ロジックを`wire.is_calibrated()`に一本化したのは、detect Lambdaと
文字列（センサ表示名）で二重に判定を持たせると、将来センサ種別が増えた時に
片方だけ更新し忘れる事故を避けるため。

## 何が覆ったか

`docs/piezo.md`の「`dashboard/app.js`は無改修」という記述を訂正した
（波形表示は無改修のままだが、gal前提ロジック側は改修が要った）。

## 次に何が可能になったか

将来LSM6DSO等の別の非校正センサ・生値センサを足しても、`sensor_type`の
帯域（`docs/wire_format.md`）に沿って番号を振るだけでdashboard側は
自動的に正しく振る舞う（`calibrated`はsensor_type由来で機械的に決まるため）。
