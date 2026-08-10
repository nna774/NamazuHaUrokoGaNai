# TlsMemPoolの`sCurrentOutstanding`が実機で大きく負に振れた件の原因調査

## 経緯

実機ログ(device_id=4294967295、fake-sensor機、長時間稼働)で以下を観測した。

```
[tls-pool] calloc FAILED for 16717 bytes (pool exhausted, call #353147,
outstanding=-1073132 peak=48233)
```

`sCurrentOutstanding`(現在確保中の合計バイト数、本来0以上のはず)が-1073132という
大きな負値になっていた。会計が壊れている疑いがあるため、`poolAlloc`/`poolCalloc`/
`poolFree`/`mergeWithNext`(`firmware/lib/TlsMemPool/TlsMemPool.cpp`)のポインタ演算を
監査し、あわせて「単一のuploaderTaskからしか呼ばれない」という設計前提
(`TlsMemPool.h`冒頭)が実機で本当に成立しているかも確認した。

## 分かったこと

**原因は`sCurrentOutstanding`の加算値と減算値が非対称になっている単純な会計バグで、
ブロックのリンクリスト自体(`BlockHeader`のmagic/size/physNext/physPrev)は破損して
いない。**

- `poolCalloc()`は要求された生のバイト数(`nmemb*size`、アライン前)を加算する
  (`sCurrentOutstanding += bytes;`)。
- `poolFree()`はブロックヘッダの`size`(実際に確保されたサイズ)を減算する
  (`bytes = b->size; ... sCurrentOutstanding -= bytes;`)。これは要求値より
  大きくなりうる:
  - `poolAlloc()`の分割時は`alignUp()`で8バイト境界に切り上げた`need`を`b->size`に
    入れる。要求バイトとの差は最大7B。
  - 分割の余りが`sizeof(BlockHeader)+kAlignment`(=24B)以下だと**分割自体を
    スキップし**、`b->size`は元の(要求よりずっと大きいこともある)空きブロックの
    サイズのまま残る。

  どちらの経路も「減算側が加算側を上回る」方向にしかズレないため、alloc/freeを
  繰り返すたびに`sCurrentOutstanding`が着実に負側へドリフトする。観測値
  (call #353147で-1073132、平均すると1呼び出しあたり約-3.04B)は、この理論上の
  ズレ幅(0〜24B、アラインメントだけでも期待値3〜4B程度)とよく符合する。

- リンクリストの整合性は個別に追ったが破綻箇所は見つからなかった。特に、
  `poolFree()`内で前方結合(`mergeWithNext(b)`)してから`b->physPrev`を見て後方結合
  (`mergeWithNext(b->physPrev)`)する順序について——`mergeWithNext(b)`は`b`自身の
  `physPrev`フィールドを書き換えないため、直後に読む`b->physPrev`はstaleにならない。
  分割時のヘッダ配置・アラインメント境界(`remain`がちょうど閾値の場合等)も
  読んだ限り破綻していない。

- 単一タスク前提は`main.cpp`を確認した限り現状も成立している。TLSを使うのは
  `gUploader`のバッチPOSTと`performPullOta`(`checkAndPerformPullOta`経由、
  呼び出し元は`uploaderTask`ループ内、main.cpp:616)の2箇所のみで、いずれも
  Core0の`uploaderTask`に閉じている。`samplingTask`(Core1)はTLSに触れず、
  `WiFi.onEvent`等の別経路でmbedTLSを呼ぶコードも見当たらなかった。したがって
  今回の現象は競合破損ではない。

## 実害の評価

見つかった範囲では統計カウンタ(`sCurrentOutstanding`/`sPeakOutstanding`)だけが
壊れており、確保領域が重なるような静かなヒープ破壊が起きている根拠は無い。
ただし実害としては「プール枯渇の誤検知が実際より早く出る」という形で既に
顕在化している(観測ログのFAILEDがその一例)。

## 次にやること

- `poolCalloc`側も`poolAlloc`が返したブロックの実サイズ(`headerOf(p)->size`)を
  見て加算するよう揃え、加算/減算を対称にして根本原因を解消する。
- `poolFree`にO(1)の防御チェック(`size`がプール全体を超えていないかの範囲チェック、
  `sCurrentOutstanding`が負に落ちた時点での即時Serial警告)を足し、次に同種の
  想定外が起きた時にもっと早く気付けるようにする。
- アロケータのポインタ演算部分をArduino/mbedTLS非依存の別ファイルへ切り出し、
  `firmware/test/run.sh`と同じ枠組みでホストg++の乱数ストレステスト(全ブロックの
  size合計+ヘッダ分==プール全体、`sCurrentOutstanding`が負にならない、隣接する
  freeブロックが2つ残らない、を検証)を書く。
