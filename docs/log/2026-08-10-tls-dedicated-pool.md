# mbedTLS専用固定プールを実装し、実機で謎のハング原因を特定した（2026-08-10）

## 背景

[log/2026-08-10-tls-alloc-probe.md](2026-08-10-tls-alloc-probe.md)で用意した実測プローブ
(`firmware/lib/TlsAllocProbe`、`env:tls-alloc-probe`)を、実機（予備基板、テスト用
device_id=UINT32_MAX、`env:fake-sensor`ベース、spillに142本の未送信バッチを溜めた状態）
で走らせた。

## 実測結果: TLSハンドシェイクの実際のフットプリント

1回目のバックフィル送信(新規ハンドシェイク、`http_.POST()`まで約2.4秒)で:

```
calls=4783 frees=4745 fails=0 outstanding=41825 peak=48304 largest_single=16717 total_requested=325804
```

- 最大単発確保: **16717バイト**。PR #54で見つけた`MALLOC_CAP_8BIT`側の最大空きブロック実測値
  (17396バイト)、`newBatch()`が必要とする18038バイトとほぼ同じ桁——**TLS側の単発ブロックが
  newBatch()と同じ土俵で断片化を奪い合っている**という仮説をそのまま裏付ける数値だった。
- ピーク同時確保: 48304バイト。通算確保回数4783回(mbedTLSは細かい確保を大量に行う)。
- 接続を使い回す設計のため、送信完了後もoutstanding=41825バイトが解放されず残ったまま
  （`spillCount_ > 0`の間は`Uploader::closeIdleConnection()`に到達しないため）。

2回目・3回目の送信は再現性高く全く同じ数値(largest_single=16717など)を示した——測定は
ノイズではなく安定した実測値。

## 実機で「無期限に無応答」バグを再現し、正体を特定した

接続使い回し中の様子を10分間観察したところ、最初の成功送信の直後、mbedTLS呼び出しが
ごく小さく2回動いた(+4回/+4回、確保量の増減なし)のを最後に**完全に無音**になった
（`postBatch begin`の行すら出ない）。パニックも再起動もせず、10分経っても復帰しなかった。
これはdocs/design.mdが2026-08-09に記録した「1本送信成功後、パニックもせず無期限に無応答」
という device1 の実障害パターンと一致する。

原因を特定するため、`batch-uplink`の`Uploader::pump()`自体にタイミングログを追加した
（[batch-uplink#14](https://github.com/nna774/batch-uplink/pull/14)、v2.5.0。postBatch()
自身には既にログがあったが、pump()側の分岐——WiFi状態・バックオフ・spill読み込みの各段階
——には何も無く、「postBatch begin」が一度も出ないまま止まって見える現象を切り分けられ
なかった）。

計装版を焼き直して同じ状況を再現したところ、正体が判明した:

```
pump: spill branch, spillCount=138
pump: loadOldestSpillPath -> /spill/00001786323931438082.bin   (この2ステップ間に約5秒)
pump: opened .../....bin len=18032
pump: read -> -1 (body=0x0)          ← malloc(18032) が失敗している
pump: backoff active (now=... next=...)  ← 以降、指数バックオフ(1s→2s→...→60秒上限)で
                                             同じファイルへの再試行を延々と繰り返す
```

**「無期限に無応答」の正体は、ソケットやTLSハンドシェイクでのブロッキングではなく、
同じ1本の退避ファイルに対する`malloc(18032)`が指数バックオフの上限(60秒)に達しても
永遠に失敗し続けるだけの、単純な——しかし外からは検知不能な——リトライループだった。**
パニックしないのは当然で、コード上は正しく「失敗を検知してバックオフする」という
想定通りの分岐を踏み続けているだけ。ただし出力が一切無いため、運用上は「固まった」
としか見えない。

`malloc(18032)`が失敗する理由は実測プローブの結果とそのままつながる: 使い回し中の
TLS接続が握ったままの約41.8KB(outstanding)が一般ヒープの連続した空き領域を奪っており、
newBatch()と全く同じ理屈で18032バイトの連続ブロックを確保できなくなっていた。

## 対策: mbedTLS専用固定プールを実装した

`firmware/lib/TlsMemPool`を新規実装し、`mbedtls_platform_set_calloc_free()`でmbedTLSの
確保/解放だけを専用の64KiB固定プールへ隔離した（`docs/design.md`の予備案(3)の本実装）。

- プールサイズ64KiB: 実測ピーク48304バイトに約35%の余裕を持たせた値。
- プールは`setup()`冒頭、WiFi/Uploader/OTA初期化より前に`malloc()`で一度だけ確保する
  （static配列にはしない——`dram0_0_seg`のリンク時静的配置制限に当たることは
  [log/2026-08-10-newbatch-buffer-pool-handoff.md](2026-08-10-newbatch-buffer-pool-handoff.md)
  で実証済み）。
- 中身は境界タグ方式のシンプルなfirst-fitアロケータ(隣接空きブロックを即時結合)。
  プールが尽きたらcalloc失敗(nullptr)を返すだけで、mbedTLS自身が想定している
  エラー経路(TLS操作失敗→呼び出し側の既存の指数バックオフ)に安全に委ねられる。
  一般ヒープは一切奪わないため、`newBatch()`側はTLSの都合に一切影響されなくなる。
- `env:tls-alloc-probe`ビルド(計測用、素通しラッパー)とは`main.cpp`のifdefで排他。
  通常ビルド(esp32dev/adxl355、OTA含む)は既定でこのプールが有効になる。

## 確認したこと・まだやっていないこと

- `pio run -e esp32dev -e adxl355 -e tls-alloc-probe`のビルド成功、
  `firmware/test/run.sh`（wireバイト等価テスト）も確認。
- OTA(docs/ota.md、未着手)は`Uploader`とは別のローカル`WiFiClientSecure`を使うが、
  同じグローバルフックの対象になる。OTA先(S3/CloudFront)のTLS footprintは未測定
  ——実装時に別途実機で確認すること。
- device1/device2への投入判断はまだ。

## 実機検証: 狙った効果は確認できたが、新しい壁にぶつかった

`env:fake-sensor`にこのプールを乗せ、詰まらせたままのテスト機（spill 138本、
同じ最古ファイルで`malloc(18032)`が指数バックオフの上限まで失敗し続けていた状態）
へ焼き直して確認した。

**効果はあった。** 起動後最初の試行で、以前は一度も通らなかった`malloc(18032)`が
成功し(`read -> 18032`)、`postBatch begin`→`http_.begin()`→`http_.POST() start`
まで到達した(以前のログでは`read -> -1 (body=0x0)`で毎回止まっていた箇所)。

**しかしその直後、`fopen`の連続失敗→`TASK_WDT`パニック→再起動、を繰り返すように
なった。** 2回目のクラッシュは`addr2line`でバックトレースを解読して原因を特定した:

```
Uploader::loadOldestSpillPath()
  → File::openNextFile()  (spillディレクトリの列挙)
    → std::make_shared<VFSFileImpl>(...) → operator new()
      → 確保失敗 → 例外 → catchされず std::terminate() → abort()
```

**これはTlsMemPool自体のバグ(メモリ破壊)ではない。** アロケータのロジックは
正しく動作しており、実際に`malloc(18032)`を1回通してもいる。原因は、TLS用に
先取りした64KiB固定プールと、`kMaxRamBatches=6`(esp32dev機、最大108KB)の
RAMキューが、spillに詰まったまま(malloc失敗が続く間)同時に一般ヒープを
圧迫し続け、**一般ヒープが本当に底を突いた**こと。底を突いた瞬間、たまたま
`openNextFile()`内部の小さな`new`がそれを踏み、Arduino環境では例外が正しく
処理されずクラッシュに直結する。

副産物として、**TlsMemPoolの有無に関係なく以前から存在した既存の頑健性バグ**
も見つけた——ヒープが極端に逼迫した状態で`loadOldestSpillPath()`のディレクトリ
列挙が走ると、`new`の失敗が例外化されて握りつぶされずabortする。この機体の
ヒープ逼迫のシビアさを踏まえると、TlsMemPoolを入れる・入れないに関わらず
起こり得た潜在バグだったと考えられる。

今回の検証(spill 138本の詰まり＋FakeSensorが休みなく新規バッチを作り続ける
状態)はかなり厳しい人工的ストレスだが、実機のバックフィル時にも近い状況は
起こりうる。検討した選択肢と判断（2026-08-10、ユーザーと相談）:

1. **採用、実施済み。** TLSプールを実測ピーク(48304B)から52KiBまで削り、
   一般ヒープの余裕を増やす。65536→65536-52*1024の差分ぶん一般ヒープが
   広がる。TLS側のcalloc失敗リスクは上がるが、mbedTLSはC実装なので
   TLS操作失敗→既存の指数バックオフという安全な経路に落ちるだけで、
   abortには繋がらない（Aの結論、詳細下記）。
2. **保留(2026-08-10)、作戦としては残す。** `kMaxRamBatches`を減らし
   RAMキューの最大占有量を下げる。`config.h`のコメント通り「溢れたぶんは
   LittleFSへ逃げるのでデータは落ちない」——`kMaxRamBatches`はspillの
   総容量(16MB機で~5.6時間分)とは独立で、減らしても総バッファ容量は
   減らない。副作用は「詰まった時によりflash書き込みが増える(摩耗・
   レイテンシ)」だけで、データロスのリスクは増えない。今回踏んだクラッシュ
   (RAMキュー最大108KB+TLSプールが同時にヒープを圧迫)に直接効くレバーでも
   ある。1(プール縮小)だけで足りるかを見てから、必要なら着手する。
3. **別PRで対応(実施中)。** `loadOldestSpillPath()`側の`new`失敗を先に直す
   (TlsMemPoolと無関係な既存の頑健性バグとして独立に対応する価値がある)。

**実機(device1/device2)への投入判断はまだ。テスト機での検証も継続中。**

## 続報: `loop()`/`uploaderTask`のLittleFS競合、mutexではなくvolatile publishで直す

Aの効果検証中、テスト機で新しいクラッシュを踏んだ: `assert failed: lfs_file_close
lfs.c:6080 (lfs_mlist_isopen(...))`（LittleFS内部の整合性チェック違反）。addr2lineで
バックトレースを解読したところ、`main.cpp`の`loop()`(Core1、ディスプレイ更新用に
250msごとに呼ばれる)が呼ぶ`Uploader::oldestQueuedStartUs()`(内部で`loadOldestSpillPath()`
を叩きLittleFSへアクセスする)が、`uploaderTask`(Core0)の`pump()`(同じくspillへ
アクセス)と**ロックなしで同時にLittleFSへアクセスしていた**ことが原因と特定した。

これは今回のTlsMemPool/kMaxRamBatches/例外処理のどれとも無関係な、以前から存在した
独立のバグ——普段は表示更新(250ms周期)とspill読み込みのタイミングがめったに重ならず
表面化しないが、今回のような高頻度リトライ(backlog多数)で競合窓が広がり顕在化した。

design.mdが元々「`uploaderTask`を吸い出し/送信の2タスクに割る時は`ram_`にmutexが要る」
と書いていたのと似た話に見えるが、**2タスク分離とは別問題**と判断した——`loop()`は
分離後も変わらず存在する第3のタスクなので、分離してもこの競合は消えない。むしろ
LittleFSに触るタスクが増えて競合の芽が増える。

対策は、`Uploader`へmutexを持ち込むのではなく、このファイルに既にある「1書き手・
1読み手のvolatile」パターン(`gDispIntensity`等、測定タスクが書きloopが読む)を
踏襲した: `uploaderTask`(Core0)側でbacklog年齢を計算し`gBacklogAgeS`(volatile)へ
publish、`loop()`(Core1)はそれを読むだけにしてLittleFSアクセスをCore0側へ一本化した。
mutexなしで競合が消える、小さく安全な修正。

実機で10分間の連続監視を行い、このクラッシュの再発は無いことを確認（同時に
`malloc(18032)`の間欠的な失敗・ネットワーク層の失敗(`DNS Failed`/`code=-1`/`code=-3`/
`GROUP_KEY_UPDATE_TIMEOUT`)は残るが、いずれも安全にbackoffへ落ちるだけでクラッシュ
しない）。

## 続報2: device1/device2の非対称性を`kMaxRamBatches`の差で説明できるかもしれない

`config.h`では`kMaxRamBatches`がADXL355(2号機)=3・それ以外(1号機)=6で、RAMキューの
最大占有量は1号機108KB・2号機54KBとちょうど倍の差がある（バッチ本体は両機とも同じ
18KB）。今回特定した「RAMキューがヒープを圧迫しmalloc(18032)を詰まらせる」構図が
正しければ、キュー上限が倍の1号機の方が先にこの罠にハマりやすい——2026-08-09の
調査ログで「device2は同じ夜に再現していない」としていた非対称性と符合する仮説。

**ユーザーの実運用での体感と一致する裏付けが取れた**: 「インターネット断のあと、
1号機はいつも帰ってこれず、2号機は毎回復帰できている」——単発の観測ではなく毎回の
一貫した経験則とのこと。後付けの仮説にしては綺麗にハマりすぎている面はまだ残るが、
偶然の一致とは考えにくい強さの裏付け。`kMaxRamBatches`縮小(選択肢2、現在1号機のみ
6→2で実験中)が実機投入すべき本命の対策である可能性が高まった。

## 続報3: `malloc(18032)`が延々失敗し続ける件、`MALLOC_CAP_8BIT` vs `INTERNAL`の疑いを再検証

続報1のvolatile publish修正後の実機ログを精査したところ、`DNS Failed`は1回しか
出ておらず、その後延々続いていた失敗は`malloc(18032)`単体だった。`heap_free`は
約59000〜59084で終始安定（右肩下がりなし=リークではない）にもかかわらず、
同じ`ESP.getMaxAllocHeap()`(`MALLOC_CAP_INTERNAL`基準)は毎回45044という
`malloc(18032)`に対して十分すぎる値を報告し続けていた。

これはPR #54の原因(`MALLOC_CAP_INTERNAL`が`MALLOC_CAP_8BIT`を過大報告する)と
同じ構図に見える——ただし今回は当時と違い、TlsMemPoolでTLS分は既に隔離済みの
状態でも起きている。実際に`malloc()`が使う`MALLOC_CAP_8BIT`側の実測値がまだ
ログに出ていなかったため、[batch-uplink#17](https://github.com/nna774/batch-uplink/pull/17)
（v2.8.0）で`pump()`の読み込み失敗ログに`heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)`
を追加した(`maxblock_internal`/`maxblock_8bit`のペアで両方出す)。firmware側の
pinもv2.8.0へ追従済み。

### 確定: `MALLOC_CAP_8BIT`側は本当に18032未満まで断片化していた

v2.8.0を焼いたテスト機の実機ログで、`malloc(18032)`失敗の瞬間を捕まえた:

```
pump: read -> -1 (body=0x0) heap_free=77248 maxblock_internal=45044 maxblock_8bit=17396 t=16212998
```

**`maxblock_8bit=17396`——要求サイズ18032に対し実際に636バイト足りていなかった。**
一方`maxblock_internal`(`ESP.getMaxAllocHeap()`、`MALLOC_CAP_INTERNAL`基準)は
45044と、実際には確保できない量を「まだ十分余裕がある」と誤報告し続けていた。
`heap_free`(77248、総空き容量)は潤沢なのに`MALLOC_CAP_8BIT`側の**連続した**
最大ブロックだけが要求未満——リークではなく純粋な断片化が原因と確定した。

その後30分近く監視を続けたが、`maxblock_8bit`は17396のままピクリとも動かず、
`read -> -1`が指数バックオフ(60秒上限)で延々繰り返された。**値が完全に一定**
ということは、断片化がこの機体のこの状態で安定した局所最適に嵌っている
（悪化も改善もしない）ことを意味する。

`maxblock_8bit`の実測値17396は、[log/2026-08-10-tls-alloc-probe.md](2026-08-10-tls-alloc-probe.md)
でPR #54が最初に実測した値(17396バイト)と完全に一致する——この機体では
`MALLOC_CAP_8BIT`側の最大連続ブロックが構造的にこの近辺で頭打ちになりやすい
ということ。TlsMemPool導入でTLS分は隔離済みだが、それでもこの上限を割ることが
あるため、`newBatch()`(18038B)・`Uploader`の退避ファイル読み込み(18032B)
どちらも、この機体では時折このブロック上限に阻まれうる。

これは`ESP.getMaxAllocHeap()`をヒープ余裕の判断に使うと**実際より楽観的な
数値が出て見誤る**ことの再確認でもある——今後この機体系列で確保可否を診断
する時は`MALLOC_CAP_8BIT`側を見ること。挙動自体(malloc失敗→指数バックオフで
リトライ)は既に安全に処理されクラッシュには繋がらないが、**単純リトライでは
この断片化状態は自然には解消しない**ことも同時に確認された——`heap_free`に
まだ余裕(77248B)があっても、17396バイトという連続ブロックの天井そのものを
動かす何か(該当ファイルの送信成功による退避ファイル削除、他の大きな確保の
解放、再起動等)が起きない限り、同じ退避ファイルへの`malloc(18032)`は
恒久的に失敗し続ける。
