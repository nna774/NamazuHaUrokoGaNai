# coredump自動クラウド送信構想の設計を詰めた

[2026-08-29-coredump-auto-upload-design-discussion.md](2026-08-29-coredump-auto-upload-design-discussion.md)の続き。実装はまだしていないが、チャットでの検討により以下の形にほぼ収束した。

## クラウド側

- **新規Lambdaは立てず、`lambda/ingest`に`POST /coredump`ルートを追加する。** 既存の`/`(バッチ)・`/alert`(速報)と同じ`auth.verify(device, raw, sig)`をそのまま通せる——認証コードを増やさずに済む。
- **保存先は既存の`data`バケット**（`terraform/s3.tf`で既にpublic access block済み・非公開）に`coredump/`という新prefixで置く。ただし現状の`expire-raw`ライフサイクルルールは`raw/`固定でこのprefixを拾わない。秘密が写っているかもしれない前提（[前回ログ](2026-08-29-coredump-auto-upload-design-discussion.md)参照）なので`events/`(永久)ではなく`raw/`寄りに倒し、**専用のライフサイクルルールで60日失効**にする。
- **通知はwatchdogと同じSlackチャンネル・メンションを流用**（`lambda/watchdog/handler.py`の`SLACK_MENTION`）。`batch-uplink`の`notify`ヘルパーをそのまま使う。
- **200を返すのはS3保存が成功した時だけ**。通知の成否では左右しない——batchの`devices.get_device`失敗時と同じ「主経路ではないので失敗してもACKは返す」哲学。

## デバイス側

「64KBのcoredumpパーティションは1世代しか保持しない（次のパニックで上書き）」という制約への対処として、**一旦LittleFSへコピーしてから送る**方式に決めた。これにより2つの問題を同時に解決する。

1. **単一スロット問題**: 起動直後、WiFi接続より前に(＝ネットワーク非依存のローカルflash操作だけで)coredumpパーティションの中身を`/coredump/`(LittleFS)へコピーし、コピーが終わり次第すぐ`esp_core_dump_image_erase()`でハードウェア側を空ける。次にすぐクラッシュしても、単一スロットへの上書きに戻るだけでLittleFS側のコピーは無事。
2. **クラッシュループでの溢れ**: LittleFS側は`Uploader`の`dropOldestWhenFull=true`と同じ「上限件数を決めて古いものから捨てる」方針のリングバッファにする。スロットあたり64KBに対しspillパーティションは11.87MBあるため容量そのものは問題にならないが、無制限に増えるとバッチ用spillの容量を圧迫するため上限は必要。件数は未確定（5〜10件程度を想定）。

アップロード（LittleFS→クラウド）は**新しい常駐taskを作らない**。`setup()`内、`connectWifi()`成功後・`gUploader`生成やtask起動より前に、同期的な関数呼び出しとして行う。理由:

- 過去のヒープ/スタック不足の経緯（`kMaxRamBatches`調整やバッファプール導入の顛末）を踏まえ、四六時中は動いていない仕事のために常駐taskのスタックを確保し続けたくない
- coredumpが無い起動(大半)ではディレクトリを覗いて空だと分かった瞬間に戻るので追加コストはほぼゼロ
- **`main.cpp`の`setup()`冒頭で`tlsmempool::install()`により、mbedTLSの確保は「単一TLS接続前提でサイズを見積もった固定プール」を使う設計になっている**(OTAが`gUploader->closeConnection()`を明示的に呼んでからCloudFrontへ新規接続する処理があるのと同じ理由)。coredump送信を`gUploader`生成・`batchDrainTask`/`uploaderTask`起動より前に済ませれば、その時点でTLS接続はcoredump用の1本しか存在せず、このプールの前提を自然に満たせる。後からuploaderTask稼働中に割り込ませる設計だと、この前提を壊しかねない
- WDTには頼らない。coredump送信専用の関数内は`esp_task_wdt_reset()`を挟むtaskではないため、`millis()`ベースの自前の締め切り（`WiFiClientSecure::setHandshakeTimeout(4000)`と組み合わせ、1件あたり・全体それぞれに上限）で確実に打ち切る

`Uploader`(batch-uplink)は経由させない。CLAUDE.mdに明記の通りbatch-uplinkは「測る対象に依存しない部分だけ」を持つ設計であり、coredumpの送信先・形式はnamazu固有のため、素朴な`WiFiClientSecure`+`HTTPClient`を使う独立した小さい関数にする。

ペイロードの渡し方にも注意点を1つ発見した。素朴に「LittleFSからファイル全体を1つのバッファへ読んでからPOST」すると、コアダンプは最大64KBあるため**18KBのバッチ用バッファより大きい単発mallocになる**——「バッチに比べれば誤差」という直感は誤りで、このプロジェクトが過去に苦しんだ「大きな単発malloc」を再現しかねない。`HTTPClient::sendRequest(method, Stream*, size)`が`File`をそのまま`Stream*`として渡せるため、**LittleFSの`File`ハンドルを直接ボディとして渡してストリーミング**すれば、64KBを1ブロックとして確保する必要が無くなる。

## 未確定のまま残っている点

- LittleFSリングバッファの保持件数上限
- `/coredump/`のファイル命名(採番方式)
- 実装の着手順序（プランを立ててから）

**続き**: 上記の未確定点も含めて実装プランに落とした。
[log/2026-08-29-coredump-auto-upload-plan.md](2026-08-29-coredump-auto-upload-plan.md)
