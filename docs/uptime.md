# 稼働時間（uptime）の作戦

デバイス詳細ページ（[device_overlay.md](device_overlay.md)とは別件、[progress.md](progress.md)
2026-08-07の温度トレンド追加の派生）で「最終起動からの経過時間」を出したいという
要望から。**未着手**（設計のみ）。

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
サーバ側で絶対時刻を逆算できる。これは温度トレイラー（生値のまま送り、℃換算は
サーバ側でやる）と同じ考え方（[wire_format.md](wire_format.md)）。

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

### 2.2 wire v2 トレイラーに新種別を1つ足す

`firmware/lib/NamzWire/WireFormat.h`の`TrailerType`に追加:

```cpp
enum TrailerType : uint16_t {
  kTrailerSensorTemp = 1,
  kTrailerUptimeUs = 2,  // 起動からの経過[us]（esp_timer_get_time()の生値）。バッチ先頭時点の1点
};
```

温度と全く同じ「バッチ先頭時点の1点」パターン。トレイラーは「知らないtypeは
lenぶん読み飛ばす」設計（[wire_format.md](wire_format.md)）なので、旧ファーム・
旧readerとの互換は既存の仕組みがそのまま守る。**batch-uplinkには一切触れない**
（`Batch`/`Uploader`はペイロードの中身に無関心。CLAUDE.mdの不変条件どおり）。

`lambda/common/wire.py`の`BatchMeta`に`uptime_us`プロパティを足す（`sensor_temp_raw`
と同じ形、`struct.unpack("<Q", ...)`でu64を読む）。

## 3. サーバ側: 起動時刻(boot epoch)を逆算し、再起動を検知する

ブート起点そのものはどこにも保存させない。**ingestが毎バッチ計算するだけ**:

```
boot_epoch_us = batch_start_us - uptime_us
```

新設する`lambda/common/device_meta.py`（[2026-08-07-device-detail-sensor-and-links.md](log/2026-08-07-device-detail-sensor-and-links.md)で
センサ種別を記録するのに作った、Namazu固有の静的なデバイス属性を`namazu-devices`に
`update_item`で足す型）に`record_boot_epoch()`を足す:

1. 今回計算した`boot_epoch_us`と、`namazu-devices`に保存済みの`boot_epoch_us`を比較
2. 差が閾値（TimeSyncのドリフト許容、案: ±2分）を超えていたら「再起動があった」と
   みなし、`boot_epoch_us`を更新
3. 閾値内なら何もしない（同一ブートセッション内のジッタはDynamoDB書き込みを増やさない）

この差分検知が**再起動検知そのもの**になる。`fw_version`の変化を見るより確実——
クラッシュや電源断による再起動も、`fw_version`が変わらなくても拾える。

将来欲しくなったら、閾値超え検知のタイミングで`restart_count`をインクリメントする
ことも同じ`update_item`に相乗りできる（今回は見送り、まずは「今の稼働時間」だけ出す）。

## 4. ダッシュボード表示

デバイス詳細ページ（`#device/<id>`）の情報テーブルに「稼働時間」行を1つ足す。
`api`の`/devices`・`/devices/<id>`が返す`boot_epoch_us`から`now - boot_epoch_us`を
クライアント側で計算するか、`_device_view()`側で計算済みの秒数を返すかは実装時に決める
（既存の`age_s`/`lag_s`と同じ「サーバ側で計算して返す」流儀に合わせるのが自然）。

**やるかは好み**: 温度トレンドと同じ折れ線チャートで「稼働時間」を時系列表示すると
鋸波になり、ゼロ近くに落ちた瞬間＝再起動、が一目で分かる。ただし表示のためだけに
稼働時間の時系列を保存する意味は薄い（`namazu-devices`は「今の状態」だけを持つ台帳
なので、時系列が要るなら温度と同じく別テーブルに倒す判断が要る）。まずは最新値の
1行表示だけで十分そう。

## 5. 副産物: `millis()`の折り返しバグ

`checkAndPerformPullOta()`（`firmware/src/main.cpp` line 338-353）:

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
49.7日に一度のごく短い窓なので優先度は低いが、`esp_timer_get_time()`ベースの
安全な減算比較（`(int64_t)(sNextAttemptUs - now) > 0`）に直せば同時に直る。
稼働時間トレイラーの実装（§2.1）と一緒に直すのが効率的。

他の`millis()`使用箇所（WiFi接続タイムアウト20秒・NTP再同期1時間・画面の揺れ表示）
は減算パターン＋十分小さい閾値なので折り返し安全（詳細は本ドキュメント作成時の
調査ログ参照、コミットの会話に残る）。

## 6. 未定事項

- 再起動検知の閾値（TimeSyncのドリフト許容、案の±2分が妥当か）
- `restart_count`のような累積カウンタを最初から持たせるか、まずは最新値だけにするか
- 稼働時間の時系列表示（鋸波チャート）をやるかどうか・やるなら保存先をどうするか

## 実装状況

未着手。
