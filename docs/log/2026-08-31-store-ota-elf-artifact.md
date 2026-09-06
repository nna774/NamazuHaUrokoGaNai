# OTA配信時に`firmware.elf`もS3へ保存し、coredump解析の再ビルド・SHA256モンキーパッチを不要にした

[PR#186](https://github.com/nna774/NamazuHaUrokoGaNai/pull/186)（device2のOTA配信直前
TASK_WDT再起動調査）で使ったcoredump解析手順を振り返り、ユーザーから
「モンキーパッチが要るのは、OTA配信時に何かファイルを取っておけば不要にできないか」
という指摘があった。

## モンキーパッチが必要だった理由

これまでの手順（`firmware/README.md`旧版）は、実機`fw_version`と同じコミットを
`git worktree add --detach`して手元で`pio run`し、再現した`firmware.elf`を
`esp-coredump`のシンボル解決に使っていた。この`esp-coredump`は、coredump内の
`app_elf_sha256`と渡した`.elf`のSHA256を照合し、不一致なら`ESPCoreDumpLoaderError`を
投げる——PR#186の調査では、コードは`cmp -l`でビット一致と確認できたにも関わらずこの
チェックには引っかかり、実行時モンキーパッチで警告に格下げして読み進めていた。

原因は明白だった: `esp_app_desc_t.app_elf_sha256`フィールド自体が、ビルド時に
その時点のELFから計算されて焼き込まれる**自己参照ハッシュ**であり、手元で再ビルド
すると（コード実体が同一でも）このフィールドの値そのものが変わる。つまり
「再ビルドしたelfで検証する」設計そのものが、SHA256照合とは原理的に両立しない。

## 決定: `.elf`自体を配信時にS3へ保存する

`tools/publish_ota.sh`が今まで`firmware.bin`と`.sha256`だけをS3
（`ota/<env>/<version>.bin`）へ上げていたのを、同じprefixに`firmware.elf`も
上げるよう変更した。実機adxl355構成で実測したサイズは
`firmware.bin` 1,059,120 bytes（約1.03MB）に対し`firmware.elf` 18,115,928 bytes
（約17.3MB、デバッグシンボル込み）——約17倍だが、公開バケットへの追加コストは
無視できる規模と判断した。秘密情報はすでにNVS化済みで`.bin`自体も同じバケットで
公開しているため、`.elf`を並べても公開範囲のリスクの質は変わらない。

これで**本物のビルド成果物**をそのままシンボル解決に使えるようになり、
`app_elf_sha256`は実機のcoredumpと必ず一致する。再ビルド手順・バイト比較手順・
SHA256不一致モンキーパッチが丸ごと不要になった。

`firmware/README.md`「クラッシュ後のcoredump吸い出し」・`docs/ota.md`のS3レイアウト
一覧を、S3から`.elf`を直接取得する手順に書き換えた。

## 覆らなかったこと

- `.elf`保存**より前**にOTA配信した版（過去の全バージョン）はS3に`.elf`が無いため、
  それらのcoredumpを後から調べる場合は引き続き旧手順（再ビルド＋バイト比較＋
  SHA256モンキーパッチ）が必要
- USB書き込みのみでOTA配信したことがない版も同様

## 次に可能になったこと

今後OTA配信する版については、coredump解析のたびに`git worktree`で同じコミットを
再現ビルドする手間（`pio run`の時間・ディスク）が丸ごと不要になり、
`esp-coredump`のSHA256検証も素直に通るようになる。
