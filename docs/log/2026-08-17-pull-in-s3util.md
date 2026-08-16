# s3utilをbatch-uplinkから引き上げた

## 何を決めたか

`batch_uplink.s3util`を削除するPRをbatch-uplink側に出し([PR #24](https://github.com/nna774/batch-uplink/pull/24)、マージ・タグ付けは未実施)、
このレポでは`lambda/common/s3util.py`としてローカルに引き上げた。内容は無変更(ファイルの移動のみ)。
`lambda/common/store.py`・`lambda/ingest,detect,api/handler.py`・`lambda/tests/test_store.py`・
`tools/promote_event.py`のimportを`from batch_uplink import s3util`から`common`経由に直した。

## なぜそう決めたか

`s3util`は名目上batch-uplinkの共有モジュール(Electabuzzと共有)だったが、実際にはElectabuzzは
使っていなかった。Electabuzz側は保存方針(prefix・lifecycle)がNamazuと異なる
(`raw/`は90日expireだが、ElectabuzzのGFRQバッチは累積位相で永久保存が前提)ため、最初から
独自の`lambda/s3keys.py`を持っており、キーの命名規則(20桁ゼロ埋め)だけ揃えてある形だった。
`notify`は逆に両プロジェクトが実際に使っている(Electabuzzのwatchdog Lambdaが2026-08-16に
実装され`batch_uplink.notify`を使い始めた)ため、こちらは共有ライブラリに残す。

「共有ライブラリ」の看板と実態が食い違っていたのを、実態(単一消費者)に合わせて下ろした。

## 何が覆ったか

- `CLAUDE.md`の不変条件から`s3util`をbatch-uplink組の列挙から外し、独自に持つ旨を明記した。
- `lambda/README.md`の「共通モジュール」表に`s3util.py`を移し、「共有ライブラリ」表から外した。

## 次に何が可能になったか

- batch-uplink側のPR #24がマージされ`v3.0.0`が打たれたので(2026-08-17)、
  `firmware/platformio.ini`と`terraform/build_lambda.sh`の`UPLINK_VERSION`もこのPRで
  `v3.0.0`へ上げた。`.venv`へv3.0.0を試験インストールし、`s3util`がimportできなくなった
  ことと`pytest lambda/tests`(139件)が引き続き通ることを確認済み。
- Electabuzz側は元々`s3util`を使っていないので、pinの更新は向こう側の任意のタイミングでよい。
