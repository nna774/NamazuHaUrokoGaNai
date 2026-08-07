# 稼働時間(uptime)の作戦をまとめた（実装は未着手）

## 何を決めたか

デバイス詳細ページに「最終起動からの経過時間」を出すための設計を
[docs/uptime.md](../uptime.md)にまとめた。骨子:

- ファームは`esp_timer_get_time()`（起動からの経過us、事実上折り返さない）の
  生値をwire v2の新トレイラー(`kTrailerUptimeUs = 2`)で毎バッチ送るだけにする。
  絶対時刻の計算はさせない。
- サーバ（ingest）が`boot_epoch_us = batch_start_us - uptime_us`を毎バッチ逆算し、
  前回保存値と比較する。閾値を超えてズレていたら「再起動があった」と判定して
  `namazu-devices`の`boot_epoch_us`を更新する。この差分検知が再起動検知そのもの
  になり、`fw_version`の変化を見るより確実（クラッシュ等バージョン不変の再起動も拾える）。
- 保存は新テーブルを作らず、センサ種別([2026-08-07-device-detail-sensor-and-links.md](2026-08-07-device-detail-sensor-and-links.md)で
  作った`device_meta.py`)と同じ「namazu-devicesへの部分update_item」パターンに乗せる。

## なぜそう決めたか

温度トレイラーで確立した「生値のまま送り、換算・計算はサーバ側でやる」方針
（[wire_format.md](../wire_format.md)）をそのまま踏襲した。ファームに時刻同期済みの
絶対時刻演算をさせない方が、TimeSyncのドリフトの影響を一箇所（サーバの逆算ロジック）
に閉じ込められる。

`millis()`を使わず`esp_timer_get_time()`を選んだ理由は、`millis()`が`uint32_t`ミリ秒で
**約49.7日で折り返す**のに対し、稼働時間はデバイスの生涯を通じて増え続ける値だから。
`main.cpp`は既に`esp_timer_start_periodic`で`esp_timer.h`を使っており追加依存が無い。

## 何が覆ったか

なし（新規の作戦文書）。

## 次に何が可能になったか

- 実装に進めば、デバイス詳細ページに「稼働時間」を出せる。
- **副産物**: `main.cpp`の`millis()`使用箇所を全部洗い出す過程で、
  `checkAndPerformPullOta()`（pull型OTAの再試行バックオフ）に`millis()`折り返し由来の
  潜在バグを発見した（[docs/uptime.md](../uptime.md) §5）。`sNextAttemptMs = now + backoff`
  と`now < sNextAttemptMs`（減算を介さない直接比較）の組み合わせが、49.7日境界をまたぐ
  最大60秒間だけバックオフを早期満了と誤判定しうる。実害は小さい（pull型OTAの再試行が
  最大1回早まる程度）が、稼働時間トレイラーの実装（`esp_timer_get_time()`への置き換え）
  と同時に直すのが効率的と判断し、修正はそちらに合わせて後回しにした。
