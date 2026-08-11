# 稼働時間（uptime）の作戦

デバイス詳細ページ（[device_overlay.md](device_overlay.md)とは別件、[progress.md](progress.md)
2026-08-07の温度トレンド追加の派生）で「最終起動からの経過時間」を出したいという
要望から。**実装済み・実機2台(device1/device2)へロールアウト済み**（[progress.md](progress.md)
2026-08-07〜2026-08-09、2026-08-08のボタン長押し緊急再起動で`boot_epoch_us`更新・
再起動検知も実地確認済み）。

## 1. なぜ今は出せないか

ファームは起動時刻・再起動を示す信号を一切送っていない。

- `batches_total`（`namazu-devices`台帳）はingestが`ADD`で足し続ける累積カウンタで、
  デバイスが再起動しても**リセットされない**。稼働時間の代わりにならない。
- `pending_restart_requested_at_us`（リモート再起動）・`pending_ota_version`（OTA）は
  どちらも「立てて→次のバッチ受信で消す」一回性の値。ACK後は跡形が残らないので、
  「最後にいつ再起動したか」の履歴として使えない（[remote_restart.md](remote_restart.md)
  の一回性設計そのままの帰結）。
- `fw_version`の変化を見張ればOTA起因の再起動は分かるが、クラッシュ・ウォッチドッグ
  再起動・ブラウンアウト・手動抜き差しはバージョンが変わらないので拾えない。

## 2. 送信するデータ: 起動からの経過だけを生値で送る

ファームに「今何時か」を計算させない。`batch_start_us`（バッチ先頭のUNIX時刻、
TimeSync同期済み）は既に毎バッチ乗っているので、**起動からの経過時間**だけ送れば
サーバ側で絶対時刻を逆算できる。値を生値のまま送り計算はサーバ側でやる、という
方針自体は温度トレイラーと同じ（[wire_format.md](wire_format.md)）。

### 2.1 `millis()`ではなく`esp_timer_get_time()`を使う

`firmware/src/main.cpp`は現状すべて`millis()`（`uint32_t`、ミリ秒、**約49.7日で
折り返す**）で時間を扱っている。稼働時間はデバイスの生涯を通じて増え続ける値なので、
49.7日を超えて連続稼働すると折り返しで壊れる。

`esp_timer_get_time()`（ESP-IDF、`int64_t`、**マイクロ秒**、事実上折り返さない
[2^63us ≈ 29万年]）に置き換える。`main.cpp`は既に`esp_timer_start_periodic`
（サンプリングタイマー）で`esp_timer.h`を使っているので、追加の依存は無い。

**この調査の副産物**: `main.cpp`の`millis()`使用箇所を洗い出したところ、
`checkAndPerformPullOta()`（line 338-353、pull型OTAの再試行バックオフ）に
折り返し由来の潜在バグを見つけた。[§5](#5-副産物-millis-の折り返しバグ)参照。
他の`millis()`使用箇所（WiFi接続タイムアウト・NTP再同期間隔・画面の揺れ表示）は
減算パターン（`now - before < threshold`）で書かれており、閾値も49.7日よりずっと
短いので折り返し安全。

### 2.2 wireトレイラーではなくHTTPリクエストヘッダで送る

**当初案（wire v2トレイラーに新種別を足す）は破棄した。** 理由: トレイラーは
バッチ本体の一部として`raw/`にそのままS3保存される（`ingest`の`_handle_batch`が
受信バイト列を無加工で`s3.put_object`する）。温度は「センサが測った値」で、後から
生の波形と突き合わせて調べたくなる可能性がある測定データだからトレイラーに乗せる
意味があるが、**稼働時間は「今のプロセスの状態」であって測定データではない**。
毎バッチ`raw_retention_days`（既定60日）ぶん保存され続けるのは無駄だし、そもそも
サーバが欲しいのは「今このバッチを送った瞬間の1値」だけで、過去の値を保存済み
バッチから遡って読みたい場面がない（`ota_watch`や`device_meta`が扱う他の
「プロセスの状態」——版数・センサ種別・OTA目標——も同じ理由で全部トレイラーではなく
別経路で運んでいる）。

**採用: `fw_version`と全く同じ「HTTPリクエストヘッダに乗せる」方式。**
`fw_version`は`X-Namz-Fw-Version`ヘッダで送られていて（wireペイロードには一切
乗らない）、ingestが`headers.get("x-namz-fw-version", "")`で読んでいる。これは
batch-uplink `Uploader`の`extraRequestHeaderNames/Values`（v1.6.0、[device-status-fw-version-header.md](log/2026-08-06-device-status-fw-version-header.md)）
を使っている。この配列の実装を確認したところ

> 値を毎回変えたい場合は呼び出し側がvalues配列の指す先を書き換えればよい
> （Uploaderはコピーせずポインタを保持する）
> ——`batch-uplink/src/Uploader.h`のコメントより

とあり、**まさにこの用途（毎バッチ変わる値をヘッダで送る）のために作られたAPI**
だと分かった。`kMaxExtraRequestHeaders = 4`で現状`fw_version`の1枠しか使っていない
ので空きがある。**batch-uplinkの変更もバージョンpinの変更も不要**（wire v2トレイラー
案よりさらに軽い）。

firmware側の実装（`main.cpp`）:

```cpp
static constexpr const char* kUptimeHeader = "X-Namz-Uptime-Us";
static char sUptimeBuf[24];  // int64のUS値を文字列化するバッファ
static const char* kExtraRequestHeaderNames[] = {kFwVersionHeader, kUptimeHeader};
static const char* kExtraRequestHeaderValues[] = {kFwVersion, sUptimeBuf};  // 2枠目は可変

// uploaderTaskのループでpump()を呼ぶ直前に毎周更新する:
snprintf(sUptimeBuf, sizeof(sUptimeBuf), "%lld", (long long)esp_timer_get_time());
```

`kExtraRequestHeaderValues`は`kExtraRequestHeaderNames`と同様constexprを外し、値が
実行時に書き換わる（`sUptimeBuf`を指す2枠目）ことを許した。`Uploader`のコンストラクタに
渡す`extraRequestHeaderCount`も1→2に上げた。

ingest側は`headers.get("x-namz-uptime-us", "")`を読むだけ。`lambda/common/wire.py`・
`firmware/lib/NamzWire/WireFormat.h`はどちらも変更していない（wire v2 トレイラーに
新種別を足す必要が無くなった）。

### 2.3 使い分けの原則（今回の整理）

- **センサが測った値（波形と同じ「測定データ」の一部）→ wireトレイラー**。
  例: 温度（`kTrailerSensorTemp`）。後から保存済みraw/波形と突き合わせる価値がある。
- **プロセス・デバイスの状態（測定とは別の「今の情況」）→ HTTPリクエストヘッダ**。
  例: `fw_version`（既存）、稼働時間（今回）。ingestがその場で読んで
  `namazu-devices`に反映するだけで、raw/に焼き込む必要はない。

## 3. サーバ側: 起動時刻(boot epoch)を逆算し、再起動を検知する

ブート起点そのものはどこにも保存させない。**ingestが毎バッチ計算するだけ**:

```
boot_epoch_us = batch_start_us - uptime_us
```

`lambda/common/device_meta.py`（[2026-08-07-device-detail-sensor-and-links.md](log/2026-08-07-device-detail-sensor-and-links.md)で
センサ種別を記録するために作った、Namazu固有の静的なデバイス属性を`namazu-devices`に
`update_item`で足す型。既存）に足した:

- `BOOT_EPOCH_DRIFT_THRESHOLD_US = 120_000_000`（±2分、TimeSyncのドリフト許容）
- `should_update_boot_epoch(prev_boot_epoch_us, new_boot_epoch_us) -> bool`（副作用なし）:
  未記録(`prev=None`)なら無条件でTrue、記録済みなら閾値超えのズレの時だけTrue。
  `devices.evaluate()`（欠測判定の状態遷移を副作用から分離した既存パターン）に倣い、
  再起動検知の判定ロジックをDynamoDB書き込みから切り離してテストしやすくした。
- `record_boot_epoch(device_id, boot_epoch_us)`（`update_item`本体）

`ingest`の`_handle_batch`は、リモート再起動/OTAチェックで既に読んでいる
`devices.get_device()`の結果を使い回して`prev`を得る（追加のDynamoDB読み取りは無い）。
`should_update_boot_epoch`がTrueの時だけ`record_boot_epoch`を呼ぶので、閾値内の
ジッタでは書き込みが起きない。

この差分検知が**再起動検知そのもの**になる。`fw_version`の変化を見るより確実——
クラッシュや電源断による再起動も、`fw_version`が変わらなくても拾える。

将来欲しくなったら、閾値超え検知のタイミングで`restart_count`をインクリメントする
ことも同じ`update_item`に相乗りできる（今回は見送り、まずは「今の稼働時間」だけ出す）。

## 4. ダッシュボード表示

デバイス詳細ページ（`#device/<id>`）の情報テーブルに「起動時刻」「稼働時間」の2行を足した。
`api`の`_device_view()`が`boot_epoch_us`（生値）と`uptime_s = (now_us - boot_epoch_us) / 1e6`
（計算済み秒数）の両方を返す（既存の`age_s`/`lag_s`と同じ「サーバ側で計算して返す」流儀）。
「起動時刻」は`boot_epoch_us`を`最終受信`と同じ`toLocaleString('ja-JP')`でそのまま
日時表示するだけ（`age_s`のような相対表記は付けない。頭の中で「現在時刻－稼働時間」を
逆算させないためのものなので、絶対時刻そのものを見せるのが目的）。「稼働時間」は
既存の`fmtAgoExact()`（`age_s`/`lag_s`表示と同じ粗い相対表記＋秒数併記ヘルパー）を
そのまま流用した。旧ファーム（稼働時間ヘッダ未送信）は`boot_epoch_us`が無く、
どちらも「不明」と表示される。一覧テーブルには`uptime_s`の列のみで起動時刻は出さない
（列数がすでに8つで狭い、[progress.md](progress.md)2026-08-07参照）。

**やるかは好み**: 温度トレンドと同じ折れ線チャートで「稼働時間」を時系列表示すると
鋸波になり、ゼロ近くに落ちた瞬間＝再起動、が一目で分かる。ただし表示のためだけに
稼働時間の時系列を保存する意味は薄い（`namazu-devices`は「今の状態」だけを持つ台帳
なので、時系列が要るなら温度と同じく別テーブルに倒す判断が要る）。まずは最新値の
1行表示だけで十分そう。

## 5. 副産物: `millis()`の折り返しバグ（修正済み）

`checkAndPerformPullOta()`（`firmware/src/main.cpp`、修正前は line 338-353）:

```cpp
static void checkAndPerformPullOta(const String& target) {
  static uint32_t sNextAttemptMs = 0;
  if (target.length() == 0 || target == kFwVersion) return;
  uint32_t now = millis();
  if (now < sNextAttemptMs) return;  // 直近の失敗からバックオフ中
  ...
  } else {
    resumeSamplingAfterOtaFailure("pull failed");
    sNextAttemptMs = now + kOtaRetryBackoffMs;  // 1分後に再試行
  }
}
```

`sNextAttemptMs = now + kOtaRetryBackoffMs`（加算）と`now < sNextAttemptMs`
（**減算を介さない直接比較**）の組み合わせは、`millis()`が49.7日で折り返す
**その瞬間をまたぐ最大60秒間だけ**、バックオフが実際より早く「満了した」と
誤判定されうる（`now`が折り返し直前の巨大値・`sNextAttemptMs`が折り返し後の
小さい値になる組み合わせで、符号無し比較が壊れる）。

実害は小さい: pull型OTAの目標バージョンが実際に一致していない瞬間にこの
ウィンドウを踏んだ場合だけ、1分のバックオフが1回だけ早く切れて再試行が早まる
（測定停止を招く`pauseSamplingForOta()`が1回余分に走りうる程度）。頻度は
49.7日に一度のごく短い窓なので優先度は低かったが、稼働時間の実装で
`esp_timer_get_time()`を導入するのに合わせて直した——`sNextAttemptUs`を`int64_t`に
し、`now < sNextAttemptUs`の直接比較のまま（`esp_timer_get_time()`は事実上
折り返さないので、直接比較のままで安全になる）。

他の`millis()`使用箇所（WiFi接続タイムアウト20秒・NTP再同期1時間・画面の揺れ表示）
は減算パターン＋十分小さい閾値なので折り返し安全（詳細は本ドキュメント作成時の
調査ログ参照、コミットの会話に残る）。これらは`millis()`のままにした
（`esp_timer_get_time()`への置き換えは稼働時間・OTAバックオフの用途に限った）。

## 6. 未定事項

- `restart_count`のような累積カウンタを最初から持たせるか、まずは最新値だけにするか（見送り中）
- 稼働時間の時系列表示（鋸波チャート）をやるかどうか・やるなら保存先をどうするか（見送り中）

## 実装状況

firmware（`X-Namz-Uptime-Us`ヘッダ送信・`millis()`折り返しバグ修正）・
ingest（`boot_epoch_us`逆算・再起動検知）・api（`boot_epoch_us`/`uptime_s`公開）・
ダッシュボード（デバイス詳細ページの「起動時刻」「稼働時間」行、一覧の「稼働時間」列）
まで実装済み。`firmware/test/run.sh`・`pio run`（esp32dev/adxl355両env）・
`pytest lambda/tests`は確認済み。**実機2台(device1/device2)へOTAロールアウト済み・
本番デプロイ済み**（[progress.md](progress.md)2026-08-07〜2026-08-09）。「起動時刻」行は
実機（device1）で日時が正しく出ることを本番APIで確認済み。
