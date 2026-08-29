# coredump自動クラウド送信の実装完了

[2026-08-29-coredump-auto-upload-plan.md](2026-08-29-coredump-auto-upload-plan.md)で
承認された計画に沿って実装し、PR #167（lambda/terraform）・PR #171（firmware）と
してマージした。両PRとも当初は1本のPR(#167)にまとめていたが、「lambda/terraformの
実装」と「firmware側の実装」は別の関心事だという指摘を受けて途中でPRを分割した
（#167は既にログ4本+lambda/terraform実装が積んであったため、firmware側の
uncommitな変更だけを新しいworktree・新しいブランチへ移してPR化した)。

## 実装した内容

- **lambda/terraform（PR #167）**: `lambda/ingest/handler.py`に`POST /coredump`
  ルートを追加、`lambda/common/s3util.py`に`coredump_key()`を追加、
  `terraform/s3.tf`の`data`バケットに`coredump/`prefix用の60日ライフサイクルを
  追加。計画通り。
- **firmware（PR #171）**: `firmware/lib/CoredumpQueue`を新設。起動直後・WiFi
  接続前にcoredumpパーティションをLittleFS(`/coredump/`、上限8件のリングバッファ)
  へコピーしてから`esp_core_dump_image_erase()`で空け、WiFi接続後・`gUploader`
  生成前に古い順で1件ずつクラウドへアップロードする。計画からの変更点は1つ——
  ペイロードを`Stream*`で別ストリーミングする案をやめ、HMAC署名
  (`hmacSha256Hex()`)がどのみちファイル全体をバッファへ読む必要があるため、
  そのバッファをPOSTボディにも使い回す形に単純化した。64KB(coredump
  パーティションの上限)は`setup()`内の一過性の確保でしかなく、定常状態の
  ヒープ断片化には影響しない。

## 実装中に見つかった副次的な事実

- firmware実装のExplore調査中、masterが別セッションのPR #169(device2のWDT
  タイムアウト対処をbatch-uplink側に実装)・PR #170(batch-uplink v3.3.0への
  pin更新)で進んでいることが分かった。firmware側の新しいworktreeは古いmaster
  から作っていたため、最新masterへ`git merge --ff-only`してから実装を進めた。
  コード上の衝突は無かった(PR #169/#170はUploaderのタイムアウト値追加のみで、
  今回のCoredumpQueueはUploaderを経由しないため無関係)。
- 実装中に手元のディスクが一時的に逼迫(ENOSPC)した。原因は複数worktreeに
  溜まった`firmware/.pio/build`(過去セッション分含め合計数GB)。自分の作業分の
  ビルドキャッシュは削除して対応したが、恒常的な対応はユーザー側で別途行う
  とのことで、これ以上は触っていない。

## 未了

**実機での動作確認をまだ行っていない。** `pio run -e esp32dev -e adxl355`の
フルビルドは通ることを確認したが、以下は次回以降の課題:

- 実機フラッシュ後、意図的にパニックを起こしてcoredumpパーティションに
  中身ができることを確認する
- 再起動後、LittleFSの`/coredump/`へコピーされ`esp_core_dump_image_erase()`で
  ハードウェア側が空になることを確認する
- 次のWiFi接続でクラウドへアップロードされ、S3(`coredump/`prefix)に保存される
  ことを確認する
- Slack通知が飛ぶことを確認する
- `LittleFS.begin(true)`をcoredumpコピー時と`Uploader::begin()`時の2箇所で
  呼ぶことになる二重mountが実機で問題を起こさないか確認する（計画時点から
  懸念として残っていた点）
