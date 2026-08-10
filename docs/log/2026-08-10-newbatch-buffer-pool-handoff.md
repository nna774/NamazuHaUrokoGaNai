# newBatch()失敗調査を別セッションから引き継ぎ、固定バッファプール案を検討する

## 概要

- [前回ログ](2026-08-09-device1-outage-reboot-loop-and-data-loss.md)（PR #54,
  worktree `worktree-compressed-snacking-snowglobe`）の調査を進めていた別セッションの
  応答がおかしくなったため、本セッションへ引き継いだ（**実装は無し**）
- 引き継ぎ元のworktreeにローカルのみ残っていた未pushコミット（`newBatch()`失敗の
  `MALLOC_CAP_8BIT`診断）を取り込んだ。中身は検証のうえ概ね妥当と判断したが、
  「確定した」としていた箇所は単発の実測ログしか根拠が無かったため、design.mdの
  表現を一段弱めた
- ユーザーが本セッションで独立に持ちかけた「バッファを毎回mallocせず事前確保して
  使い回す」案は、引き継ぎ元が既に固めていた設計とほぼ同じだった。当初
  「`Uploader`の所有権契約自体を変えるとElectabuzzに影響する」を理由に既存
  ドラフト（所有権契約は変えず`Batch`のデストラクタ側だけでプール返却）を
  推したが、**この理由づけ自体が誤りだった**——batch-uplinkはタグ運用（CLAUDE.mdの
  不変条件）なので、APIを変える新バージョンを切ってもNamazu側のpinを上げない
  限りElectabuzzには一切波及しない。ユーザーの指摘で訂正した。それでも
  既存ドラフトを最初の一手として推す結論自体は変えていないが、根拠は
  「影響範囲」ではなく「変更が`Batch`一箇所に閉じて実装・レビューが小さく済み、
  診断済みの問題（大きい方のバッファ）にはそれで十分効く」という点に
  差し替えた。`Uploader`の所有権契約も含めて丸ごとreference化する案は、
  タグ運用のおかげでいつでも安全に後追いできる選択肢として残る

## 引き継ぎの経緯

前回ログの「次に考えないといけないこと」にあった`newBatch()`失敗原因の特定を、
別セッション（同じworktree、PR #54のブランチ）が続けていた。ユーザーによると、
その調査の途中でセッションの応答がおかしくなったため、続きを本セッションで
引き継ぎたいとの依頼だった。

引き継ぎ元のworktree（`.claude/worktrees/compressed-snacking-snowglobe`、lock済み）を
覗くと、origin未pushのローカルコミットが1つ残っていた
（`firmware: newBatch()失敗の原因をMALLOC_CAP_8BIT診断で特定する`）。
中身は実機ログを伴う具体的な診断で、放棄するには惜しい内容だったため、
本セッションのブランチへ`git merge --ff-only`で取り込んだ（fast-forwardなので
コミット自体は改変していない。引き継ぎ元worktreeのロック・ローカル状態には触れていない）。

## 引き継いだ内容の要点（前回ログ§11・design.mdより）

- `ESP.getMaxAllocHeap()`は`heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)`を
  返す。一方`Batch`のバッファは素の`malloc()`で、実際に要求するcapabilityは
  `MALLOC_CAP_8BIT`
- 実機の`newBatch invalid`ログで両基準を並べて出すよう計装したところ、
  `maxblock_internal=45044`に対し`maxblock_8bit=17396`（必要な18038バイトに
  642バイト不足）という乖離が1回観測された
- 対策として、`Batch`に外部バッファ+解放コールバックのコンストラクタを足し
  `samplingTask`側に固定サイズの静的バッファプールを持たせる（`Uploader`の
  「ポインタの所有権を受け取り自身で`delete`する」契約は変えず、`Batch`の
  デストラクタが生バッファだけをプールへ返す）設計まで固めていた。
  batch-uplinkに`external-buffer-batch`ブランチを作っただけでコミットは無い

## 引き継ぎ時に検証したこと

`getMaxAllocHeap()`の実装は理論ではなくソースで確認した
（`~/.platformio/packages/framework-arduinoespressif32/cores/esp32/Esp.cpp`の
`EspClass::getMaxAllocHeap()`が`heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)`を
呼んでいることを直接読んだ）。ここは事実として確定してよい。

一方「`maxblock_internal`45044・`maxblock_8bit`17396・642バイト不足」という具体数値は
**単発ログ1行のみが根拠**で、再現確認はされていなかった。原因の説明としては
筋が通っている（ESP32内蔵RAMは8bitアクセス不可なIRAM専用領域を含むため、
`INTERNAL`基準の最大空きブロックが`8BIT`基準より大きく見えることはハード的にありうる）
ものの、断片化の発生源自体は前回ログでも「未特定」のまま残っていた。**この
セッションの推測には精度にばらつきがある**との指摘をユーザーから受けたため、
design.mdの当該箇所を「症状の正体はこれで確定した」から「有力な説明が単発の
実測で得られた（再現確認はまだ）」という表現へ弱めた。前回ログ本文
（[§11](2026-08-09-device1-outage-reboot-loop-and-data-loss.md#11-newbatch失敗の正体を実測で特定-malloc_cap_internalとmalloc_cap_8bitの乖離)）は
既存の運用（ログは経緯をそのまま残す。訂正は本体側=design.mdで行う）に従い、
書き換えていない。

## ユーザー提案との突き合わせ

ユーザーから独立に「`Batch`のバッファを毎回mallocせず事前確保して使い回し、
uplinkには参照だけ渡して内部の`delete`をやめてはどうか」という提案があった。
狙い（malloc/freeの反復自体をやめて断片化・容量不一致のリスクを消す）は
上記のドラフト設計と完全に一致する。

実現方法には差があり、当初は次のように書いていた: ユーザー案の「参照だけ渡して
deleteをやめる」を文字通り実装すると`Uploader::enqueue(Batch*)`の所有権契約
（ポインタで受け取り、`ram_`に積んで、スピル・送信・drop-oldestのどの経路でも
最後は自分で`delete`する）自体を変えることになり、`batch-uplink`の公開APIの
意味が変わるためElectabuzzにも影響する、と。

**これは誤りだとユーザーに指摘され訂正した。** `batch-uplink`はタグ運用が
不変条件（[CLAUDE.md](../../CLAUDE.md)）で、Namazu・Electabuzzはそれぞれ独立に
バージョンをpinしている。所有権契約を変える新バージョンを`batch-uplink`側に
切っても、Namazu側の`platformio.ini`のpinを上げない限りElectabuzzには一切
波及しない。「公開APIを変えると他プロジェクトに影響する」は、pin運用をして
いない共有ライブラリなら正しいが、この2プロジェクトの運用実態には当てはまらない。

訂正した上での結論: **前回ドラフトの設計（`Uploader`側の所有権契約は変えず、
`Batch`のコンストラクタに外部バッファ+解放コールバックを足し、デストラクタが
`free()`の代わりにコールバックでバッファをプールへ返す）を最初の一手として
推す判断自体は変えていない。** 理由は「影響範囲がElectabuzzに及ばないから」
ではなく、(1) 変更が`Batch.h`/`Batch.cpp`だけに閉じ`Uploader.cpp`のキュー管理
ロジックには触れずに済む分、実装・レビューの手間とバグ混入リスクが小さい、
(2) 実測で診断できた問題（大きい方のバッファ、約18KB）にはこれで十分効き、
`Batch`ラッパー自体（数十バイト程度、`new`/`delete`は残る）の断片化寄与は
小さいと考えられる、の2点。`Uploader`の所有権契約まで含めて丸ごとreference化
する案は却下ではなく、タグ運用のおかげでいつでも安全に後追いできる選択肢として
残しておく（例えば最初の一手だけでは足りないと分かった時の次の一手）。

## 未解決点（実装はまだ着手していない）

- プールのスロット数（RAM予算）の見積もりが未了。最悪同時生存数は
  「組み立て中の1本」+「`gBatchQueue`の深さ4」+「`Uploader::kMaxRamBatches`
  （esp32dev機=6、adxl355機=3、`extends`で値が違う点に注意）」の合計になりうるが、
  `gBatchQueue`はdrop-oldestで実際に4本同時生存することは稀にしか無いはずで、
  静的確保する分の安全側見積もりとして正しいかは要検討
- 断片化そのものの発生源（mbedTLSの一時確保が疑わしいという前例が
  `config.h`のコメントにあるが未検証）は今回も特定していない。プール化は
  発生源を特定しなくても症状を回避できる対策ではある
- `batch-uplink`の`external-buffer-batch`ブランチは作成のみでコミット無し。
  実装するかどうかの判断はユーザーへ持ち帰り

## 次に何が可能になったか

引き継ぎ元セッションの未pushの成果（診断とプール化設計）を失わずに本セッションへ
接続できた。ドラフト設計とユーザーの独立提案が同じ方向を指していたことで、
「所有権契約を変えない」実装方針の妥当性を相互確認できた。次にやるべきことは
プールのスロット数見積もりと`external-buffer-batch`ブランチでの実装そのもの
（着手はユーザー判断待ち）。

## 続報: batch-uplink側を実装し、DRAM予算の壁に当たった（同日）

### 実装したこと

- `batch-uplink`の`external-buffer-batch`ブランチに、上で固めたドラフト通り
  `Batch`の外部バッファ+解放コールバック版コンストラクタを実装した
  （`Batch::ReleaseFn`は生の関数ポインタ+`void*`。`std::function`はキャプチャ付き
  ラムダが内部でヒープを取りうるため不採用）。ホストg++のテスト(`test/run.sh`)に
  外部バッファ版のケースを追加、既存分と合わせて0 failure。
  [batch-uplink PR #13](https://github.com/nna774/batch-uplink/pull/13)を作成し、
  マージ前提で`v2.4.0`タグを先行して切った（v2.1.0/v2.2.0の前例と同じやり方）。
- Namaz側(`firmware/`)に、起動時に静的配列+`QueueHandle_t`で組んだ固定バッファ
  プール(`sBatchPool`/`gBufferPool`/`newPooledBatch()`)を実装し、
  `samplingTask`の`namzwire::newBatch()`呼び出しを差し替えた。プールが尽きた時は
  素朴なmalloc版へフォールバックする安全策も入れた。`platformio.ini`・
  `terraform/build_lambda.sh`のpinはv2.4.0へ揃えた（ついでに気づいた、
  v2.2.0→v2.3.0のfirmware側だけの先行bumpでterraform側が置き去りになっていた
  drift も今回のv2.4.0で解消した）。

### DRAM予算が理論値よりずっと小さいと判明

同時生存数の理論上限（組み立て中1+`gBatchQueue`深さ4+`kMaxRamBatches`、
esp32dev機で7本≒126KB）ぶんを静的確保しようとしたところ、リンカが
`region 'dram0_0_seg' overflowed by 107984 bytes`で即死した。

原因を実測した。`xtensa-esp32-elf-size -A firmware.elf`でプール追加前の
`.dram0.data`(25772B)+`.dram0.bss`(80328B)=106100Bと、オーバーフロー量から
逆算すると、**`dram0_0_seg`（`malloc()`が実際に使うMALLOC_CAP_8BIT領域。
IRAM分は含まない）の総容量は約124.5KiB、うち既存firmwareが約106KBを既に
静的に使っており、残り約18.5KBしか無い**と分かった。

これは前回引き継いだ実測（`ESP.getMaxAllocHeap()`のMALLOC_CAP_INTERNAL基準
45044と実際の`malloc()`が使えるMALLOC_CAP_8BIT基準17396の乖離）を裏付ける
形になった——実行時に報告される`heap_free`(78240等)はIRAMの余りをヒープに
転用した分まで合算した数字で、`malloc()`が本当に使える8bitアクセス可能な
DRAMだけで見ると、そもそも数十KB規模の予算しか無い。18KBのバッチバッファは
その予算の大部分を最初から占める。

**複数本ぶんの静的プールは、このハードのDRAM予算では原理的に不可能**と
実測で確定した。試しにプールを1本(≒18KB)だけに絞ったところビルドは通ったが
（`.dram0.bss`が98400Bまで増え、残り約392バイトしか無いところまで使い切る）、
バックログが`gBatchQueue`/`Uploader.ram_`へ積み上がる局面（＝元の`newBatch()`
失敗が実際に起きた局面）ではプールが即座に枯渇しmallocへフォールバックする
ため、**本命の障害は救えない**。平常運転時のmalloc/free頻度を下げる程度の
効果しか無く、他の用途に残るDRAM余白をほぼ食い潰すコストに見合うかは疑問。

### PSRAMは無いと実機で確定した

ユーザーから「部品を足せば使えるか」と聞かれたが、PSRAMはWROVER系モジュールが
製造時にESP32ダイと専用SPI配線（GPIO16/17相当、信号品質が要る高速配線）を
同じ缶の中で結線しているもので、**組み立て済みのWROOM系基板へ後から
ジャンパ線で足せる部品ではない**。載せ替えるなら基板ごと（WROVER搭載の
別ボード）が必要になる。

念のため実機でも確認した。`psramInit()`/`psramFound()`/`ESP.getPsramSize()`を
呼ぶだけの使い捨てビルド(`firmware/src/psram_probe_main.cpp`、
`platformio.ini`の`[env:psram-probe]`)を作り、本番機と同型の予備基板
（USBで接続、`/dev/cu.usbserial-5B320272871`）に書き込んで実測した。
このプロジェクトが使っている`esp32dev`ボードのSDK(`qio_qspi`等)は
`CONFIG_SPIRAM=1`で常にビルドされている（`tools/sdk/esp32/qio_qspi/include/
sdkconfig.h`で確認、`CONFIG_SPIRAM_BOOT_INIT`も未定義なので`psramInit()`は
スタブではなく実際にSPIで話しかける実装が動く）ため、特別なボード設定変更は
不要だった。結果:

```
[psram-probe] psramInit() -> 0
[psram-probe] psramFound() -> 0
[psram-probe] ESP.getPsramSize() -> 0 bytes
```

**PSRAM無し、確定。** この診断ビルド(`env:psram-probe`)はコミットに残す
（今後別の予備基板やハード更新を検討する時に再利用できる）。

## 続報2: 「静的配列」が間違いだったと判明し、malloc()方式で解決した（同日）

上の「複数本ぶんの静的プールは原理的に不可能」という結論は、**プールを
`static uint8_t[][]`（＝`.dram0.bss`）で確保しようとしていたのが原因**で、
ユーザーの指摘（「DRAM小さいね、staticが小さいだけでヒープはあるのでは」）で
見直した。

実際にリンカスクリプト(`tools/sdk/esp32/ld/memory.ld`)を読むと、答えが
コメントに書いてあった:

```
Note: Length of this section *should* be 0x50000, and this extra DRAM is
available in heap at runtime. However due to static ROM memory usage at
this 176KB mark, the additional static memory temporarily cannot be used.
```

`dram0_0_seg`の宣言サイズ(約121KB)は、ROM起動時の一時使用と衝突しないよう
**静的配置(.data/.bss)だけに課された保守的な制限**で、本来のDRAMは
0x50000(320KB)ある。この差分は実行時のヒープ(`malloc()`)では普通に使える、
と明記されていた。つまり静的配列をやめ、`setup()`で1回だけ`malloc()`すれば
この制限を受けない。

### 実機で検証し、6スロットで確定した

`Batch`の外部バッファプールと同じサイズを`malloc()`するだけの使い捨てビルド
(`firmware/src/pool_probe_main.cpp`、`env:pool-probe`/`env:adxl355-pool-probe`)
を作り、予備基板に書き込んで実測した(NVS未プロビジョニングでもmain.cppの
halt前に試せるよう独立ビルドにした)。

- 7スロット(126448B、理論上限そのまま)は**失敗**（`malloc() -> NULL`）。
  この時点の`maxblock_8bit=114676`に対し126448は収まらない
- 6スロット(108384B)は**成功**。確保前`free_heap=350920, maxblock=114676`、
  確保後も`free_heap=242520, maxblock=110580`が残り、この後のWiFi/TLS/
  Uploader構築に十分な余裕がある。全域read/write検証も通した
- esp32dev/adxl355両envで同じ結果（バッファサイズが両方18064Bで揃っているため）

**6スロット(＝`kMaxRamBatches=1`)を採用し、firmware側を最終化した。**
`main.cpp`の`sBatchPool`を`static uint8_t[][]`から`malloc()`一発確保へ書き換え、
`setup()`冒頭（WiFi/TLS等が何も確保していない、ヒープが一番連続している時点）で
確保するようにした。`config.h`の`kMaxRamBatches`を2→1に下げ、実測値と根拠を
コメントに残した。`env:pool-probe`は使い捨てず、`config.h`を変えた時の
実機再検証ツールとして残す。`pio run -e esp32dev -e adxl355`のリンク成功、
`firmware/test/run.sh`（wireバイト等価テスト）も確認した。

### 決着

複数本ぶんのバッファプール化は**実現できた**。`batch-uplink`の外部バッファ
機能([PR #13](https://github.com/nna774/batch-uplink/pull/13)、v2.4.0)を
採用する方針が確定し、mbedTLS専用プール化・プール化断念といった代替案は
不要になった。ただし**実機（device1/device2）への投入はまだ**——ここまでは
予備基板とホストビルドでの検証のみ。

## 続報3: 実機の結合試験で追加の問題が見つかり、プール化を一旦見送った（同日）

「決着」と書いた直後、ユーザーから「同じboard、新品の予備基板を繋いだ」と
提供を受け、実際に本番と同じパイプライン（WiFi接続〜バッチ形成〜送信）を
通しで確認する結合試験を行った。

### テスト機の用意

`tools/provision_device.py`でテスト用device_id(`UINT32_MAX`=4294967295、
将来デバイスが増えても衝突しない値として選定)を追加し、`terraform apply`で
サーバ側にもHMAC鍵を登録した（本番のingest Lambda・DynamoDBを使う。
watchdogの欠測通知が来る可能性はユーザー了承済み）。実センサ無しで
パイプラインだけ確かめるため、静穏なノイズ(重力ベースライン±小揺らぎ、
震度検知閾値には掛からない)だけを出す`FakeSensor`(`firmware/lib/FakeSensor/`)
を新設し、`env:fake-sensor`でビルドして予備基板に書き込んだ。

### 見つかった問題

1. **6スロット(108384B)は実機でsamplingTaskの生成に失敗し、パニック
   再起動をループした。** `vTaskGenericNotifyGiveFromISR`が`gSamplingTask`
   ハンドルの不定値に対してアサートしていた——`xTaskCreatePinnedToCore()`が
   戻り値未チェックのまま失敗し、100Hzサンプリングタイマだけ動き出して
   いたと見られる。前回の`pool-probe`(素のスケッチ)での検証は本番firmware
   が食う分(TFT_eSPIのフォント等)を見落としており、実機の本当の余裕は
   isolatedな測定より少なかった
2. 5スロット(90320B、`kBatchQueueDepth`を4→3に削って調整)にすると
   samplingTaskのクラッシュは止まったが、**代わりに`kMaxRamBatches=0`
   (誤って一時的に設定した値)が`Uploader::enqueue()`の`ram_.front()`を
   空のdequeに対して呼ぶ未定義動作を踏み、`Guru Meditation Error`で
   パニックした。** これはbatch-uplinkの`Uploader.cpp`に元からあった
   潜在バグで、`maxRam_=0`という運用上ありえない設定を試すまで顕在化
   しなかった。`kMaxRamBatches`は0にできないと確定
3. `kMaxRamBatches=1`(5スロット)に戻すとクラッシュは無くなったが、
   **`Uploader::pump()`が`spillCount_=4`(前回試行の残骸)を抱えたまま
   60秒間一度も送信を試みなかった**（`postBatch`のデバッグログが
   一切出ない）。プールを迂回(素のmalloc版)しても再現したため、
   プール由来ではなさそうだが、原因（WiFi接続の不安定さか、
   `loadOldestSpillPath()`の失敗か）は特定できていない

### 判断: 一旦見送り

直すたびに別の症状が出る状態が続き、「この機体の8bit可能DRAM予算が
既に限界に近く、何を積んでも他の何かを押し出す」という構造的な問題に
見えてきた。これ以上スロット数を削って粘るより、**`main.cpp`/`config.h`を
`origin/master`の状態（プール導入前）へ完全に戻し、プール化は一旦見送った。**

`batch-uplink`の外部バッファ機能([PR #13](https://github.com/nna774/batch-uplink/pull/13)、
v2.4.0)は前方互換な追加のみなので巻き戻していない——再開する時はそのまま
使える。ユーザー提案で、`FakeSensor`と`env:fake-sensor`は newBatch検証専用
ではなく実センサ無しでの結合試験全般に使い回せる汎用ツールとして残した。

次に検討する方向は2つ: (1) design.mdの予備案（mbedTLSの確保専用固定プール化。
`Batch`のバッファは増やさず、TLSハンドシェイクの一時確保だけを専用プールに
閉じ込める——今回踏んだ「プールがTLSの取り分を奪う」問題自体が起きない）、
(2) プール化自体を諦め`newBatch()`失敗時の次サンプル再試行に任せる。
**まだ決めていない。**

## 次に何が可能になったか（続報3時点）

実機の結合試験（予備基板・本番と同じingest経路）を通したことで、ホスト
ビルドや素の診断スケッチだけでは見えなかった問題（samplingTask起動失敗・
`kMaxRamBatches=0`の未定義動作・送信滞留）を本番投入前に発見できた。
device1/device2には一切触れていない。`FakeSensor`/`env:fake-sensor`という
再利用可能な結合試験の足場ができたことは今回の副産物。次のセッションでは、
mbedTLS専用プール化に切り替えるか、プール化自体を見送るかの判断から
再開する。
