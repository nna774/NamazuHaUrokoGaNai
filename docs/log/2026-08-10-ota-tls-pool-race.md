# pull型OTA時、TlsMemPoolが単一TLS接続前提を破っていた（実機で再現）

## 何が問題か

`TlsMemPool`(PR #64)はmbedTLSの確保/解放を52KiBの専用固定プールへ隔離しているが、
「TLS接続は同時に1本」という前提でサイズを見積もっている（実測ピーク48KB、余裕約8%）。
`TlsMemPool.cpp`自身のコメントで「OTA実装時にこの前提が崩れないか要確認」と
課題として残っていた。

コードを読んで具体的な競合を特定した:

- `batch-uplink`の`Uploader::pump()`はバッチPOST成功後、接続(`client_`)を使い回すため
  **閉じない**（`closeIdleConnection()`が呼ばれるのは「送るものが無くなった」時だけ）。
- `checkAndPerformPullOta()`は`uploaderTask`ループの同じ周で`pump()`の直後に呼ばれる。
  レスポンスヘッダでバージョン不一致を見つけたら、その場で`pauseSamplingForOta()`→
  `performPullOta()`が別の`WiFiClientSecure`をCloudFront向けに新規に張る。
- `pauseSamplingForOta()`がやるのは測定タイマー停止と`flushToSpill()`だけで、
  `client_`側の接続には触れない。

つまり、バッチPOST成功直後の同じ周でOTAが発火すると、**ingest向けの接続が
開いたままOTA先への2本目のTLS接続を張る**ことになり、単一接続前提で見積もった
プールを超えうる。

## 対策

`batch-uplink` v2.9.0（[PR #18](https://github.com/nna774/batch-uplink/pull/18)）で
`Uploader::closeIdleConnection()`(private)を`closeConnection()`として公開し、
`pauseSamplingForOta()`内で`flushToSpill()`の直後・OTA取得を始める前に呼ぶよう
`firmware/src/main.cpp`を直した（[PR #68](https://github.com/nna774/NamazuHaUrokoGaNai/pull/68)）。
`lib_deps`/`UPLINK_VERSION`もv2.9.0へ揃えた。

## 実機で確認

`device_id=4294967295`（予備基板、`env:fake-sensor`、本番のdevice1/device2とは別）で検証。

**1回目: 修正前のファーム(`40d87cc-dirty`)を、修正後のビルド(`9e8d087`)へOTAさせて
実際に予想通りの競合を再現した。**

```
[ota-pull] update available: 40d87cc-dirty -> 9e8d087
[ota] start: pausing sampling, flushing queue to spill
[ota] flushed 0 batch(es) to spill
[ota-pull] fetching https://namazu.dark-kuins.net/ota/esp32dev/9e8d087.bin
[tls-pool] calloc FAILED for 16717 bytes (pool exhausted, call #353147, outstanding=-1073132 peak=48233)
[ssl_client.cpp] SSL - Memory allocation failed
[ota-pull] failed: 0 (HTTP error: connection refused)
[ota] pull failed: resuming sampling
```

理論通り、ingest接続を閉じないままOTA先への新規TLS接続を試み、プール枯渇で
ハンドシェイクが失敗した。クラッシュはせず、既存の指数バックオフ(1分)で
安全に縮退している（想定通り）。

`outstanding=-1073132`という負の値は、確保/解放カウンタの集計自体が既におかしい
兆候（このプロセスの寿命が長く`sCallCount`が35万回を超えている影響の可能性がある）。
プールの会計自体に別の不具合がある可能性は残るが、今回の主題（同時2接続の競合）は
上記ログで確定できたため深追いはしていない。**要フォローアップ。**

**1分後の2回目の自動リトライでは成功した**（`[ota-pull] write OK, restarting`）。
同じ修正前ファームでの再試行が成功したのは、たまたまその周でingest接続が
既に閉じていた（`pump()`が「送るものが無い」周だった）ためと考えられる——
**レースはタイミング依存で決定的ではない**、という点も実機で裏付けられた形になる。

再起動後は`fw=9e8d087`(修正版)で正常起動(`reset_reason=SW`)、`tls-pool installed:
53248 byte`(=52KiB)、`pending_ota_version`はサーバ側で自動クリアされ
(`ota_watch.py`の`reached_target()`)、以後の送信も正常。

## まだ確認できていないこと

- 修正版ファーム自身がOTA発火時に確実に接続を閉じてから新規TLS接続を張るかは、
  今回は「次のOTAターゲットが無い」ため未検証（1回目の失敗は修正前ファームの
  挙動であって、修正の効果そのものではない）。次のコミットを新しいOTAターゲットに
  して同じ手順で追検証する。
- `tls-pool`の確保/解放カウンタの負値（上記）。
- device1/device2への投入判断はまだ。
