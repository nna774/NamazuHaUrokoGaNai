# loop()とuploaderTaskがロックなしでLittleFSへ同時アクセスしていたクラッシュを直す（2026-08-10）

## 背景

mbedTLS専用固定プール(TlsMemPool、別PR)の実機検証中、送信リトライを高頻度で
繰り返す状況を作って観察していたところ、新しいクラッシュを踏んだ:

```
assert failed: lfs_file_close lfs.c:6080 (lfs_mlist_isopen(...))
```

LittleFS内部の整合性チェック違反。`addr2line`でバックトレースを解読したところ、
`main.cpp`の`loop()`(Core1、ディスプレイ更新用に250msごと呼ばれる)が呼ぶ
`Uploader::oldestQueuedStartUs()`(内部で`loadOldestSpillPath()`を叩きLittleFSへ
アクセスする)が、`uploaderTask`(Core0)の`pump()`(同じくspillへアクセス)と
**ロックなしで同時にLittleFSへアクセスしていた**ことが原因と特定した。

これはTlsMemPoolやTLS周りの変更とは無関係な、以前から存在した独立のバグ——
普段は表示更新(250ms周期)とspill読み込みのタイミングがめったに重ならず表面化
しないが、高頻度リトライ(backlog多数)で競合窓が広がり顕在化した。

## 対策

`design.md`が元々「`uploaderTask`を吸い出し/送信の2タスクに割る時は`ram_`に
mutexが要る」と書いていたのと似た話に見えるが、**2タスク分離とは別問題**と
判断した——`loop()`は分離後も変わらず存在する第3のタスクなので、分離しても
この競合は消えない。むしろLittleFSに触るタスクが増えて競合の芽が増える。

対策は、`Uploader`へmutexを持ち込むのではなく、`main.cpp`に既にある「1書き手・
1読み手のvolatile」パターン(`gDispIntensity`等、測定タスクが書きloopが読む)を
踏襲した: `uploaderTask`(Core0)側でbacklog年齢を計算し`gBacklogAgeS`(volatile)へ
publish、`loop()`(Core1)はそれを読むだけにしてLittleFSアクセスをCore0側へ
一本化した。mutexなしで競合が消える、小さく安全な修正。

## 確認したこと

実機で10分間の連続監視を行い、このクラッシュの再発は無いことを確認
（同時に発生していた`malloc(18032)`の間欠的な失敗・ネットワーク層の失敗は
残るが、いずれも安全にbackoffへ落ちるだけでクラッシュしない）。

`pio run -e esp32dev -e adxl355 -e fake-sensor`のビルド成功、
`firmware/test/run.sh`(wireバイト等価テスト)も確認した。

## 次に何が可能になったか

TlsMemPool等、送信リトライ頻度が上がりうる変更を安全に投入できる土台が
できた。この修正自体はTLS対策と独立なので単体でも意味がある。
