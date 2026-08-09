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
  使い回す」案は、引き継ぎ元が既に固めていた設計とほぼ同じだった。ただし
  「uplinkには参照だけ渡してdeleteをやめる」という提案の細部は、`Uploader`の
  所有権契約（ポインタで受け取り自身でdeleteする）自体を変える方向であり、
  batch-uplinkの公開APIを壊しElectabuzz側にも影響する。既存ドラフトの
  「所有権契約は変えず`Batch`のデストラクタが解放コールバックでプールへ返す」
  方式のほうが影響範囲が狭く優れていると判断し、その旨を伝えた

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

ただし実現方法には差がある。ユーザー案の「参照だけ渡してdeleteをやめる」を
文字通り実装すると、`Uploader::enqueue(Batch*)`が現在前提にしている
「ポインタの所有権を受け取り、`ram_`に積んで、スピル・送信・drop-oldestの
どの経路でも最後は自分で`delete`する」という契約そのものを変えることになる。
これは`batch-uplink`の公開APIの意味を変える変更で、Electabuzzも同じ
`Uploader`を使っている（[CLAUDE.md](../../CLAUDE.md)の不変条件）ため影響範囲が
両プロジェクトに広がる。

これに対し前回ドラフトの設計は、**`Uploader`側の所有権契約は一切変えない**。
`Batch`はこれまで通りポインタで受け渡され`delete`もされる——変わるのは
`Batch`の内部実装だけで、コンストラクタに外部バッファと解放コールバックを
渡せるようにし、デストラクタは`free()`する代わりにコールバックでバッファを
プールへ返す。呼び出し側（`Uploader`・`samplingTask`双方）から見た振る舞いは
「`new`して使って`delete`する」のまま変わらないため、API境界の変更が
`Batch.h`の追加コンストラクタ1つで済み、Electabuzz側は（外部バッファを
使わない限り）無改修で動き続ける。**こちらのほうが影響範囲が狭く、この方向で
進めるのが良いと判断し、その旨をユーザーに伝えた。**

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
