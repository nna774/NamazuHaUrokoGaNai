# タスク分割版をテスト機(FakeSensor)へ焼いて実機確認した（2026-08-11）

## やったこと

`uploaderTask`の2タスク分割（PR #79）とbatch-uplinkのUploader mutex化
（PR #22、未マージ）を組み合わせた状態で、テスト機（`env:fake-sensor`、
device_id 4294967295）へ実際に焼いて動作を見た。

`platformio.ini`のlib_depsは一時的にローカルの`batch-uplink`
（`uploader-task-split-mutex`ブランチ、mutex込み）を指すよう書き換えて
ビルド・書き込みし、確認後にv2.12.0（マージ済みタグ）へ戻した——mutex無しの
Uploaderと2タスク化したfirmwareの組み合わせは、まさに今回直そうとしている
競合を実機で再現しかねないため、検証中だけの一時的な組み合わせとして扱った。
このコミットには含めていない。

`pio run -e fake-sensor -t upload --upload-port /dev/cu.usbserial-5B320272871`
で書き込み成功。シリアル出力はpyserialで直接読んだ（`pio device monitor`は
非対話環境のバックグラウンド実行だとterminosエラーで使えなかった）。

## 確認できたこと

- 書き込み後、クラッシュ・再起動ループなしで継続動作（120秒以上、Guru
  Meditation Error・LittleFS assertどちらも観測されず）
- `[uplink-debug] enqueue #7 ... -> [uplink-debug] pump: ram branch ->
  postBatch(ram) -> 1`という一連の流れを実際に2周期分（約30秒間隔、
  `kBatchSeconds=30`と一致）観測——`batchDrainTask`が`gBatchQueue`から吸い出して
  `enqueue()`、送信タスクが`pump()`でRAMキューから拾って送信、という新しい
  経路が実際に正常系で動くことを確認した

## 確認できていないこと

- 本来の目的だったシナリオ（WiFi瞬断でuploaderTaskが長時間ブロックする間も
  `batchDrainTask`が動き続けgBatchQueueが溢れない）はまだ未検証。今回は
  平常時の動作確認のみ
- OTA・リモート/手動再起動といった既存シナリオの実機確認もまだ

## 次に何が可能になったか

正常系での組み合わせ動作は実機で裏が取れたので、batch-uplink PR #22の
レビュー・マージ・タグ付けを進めてよい状態になった。WiFi瞬断シナリオの
実機確認は別途行う必要がある。
