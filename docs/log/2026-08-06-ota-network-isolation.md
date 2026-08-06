# device 2にOTA対応ファームを焼き、push OTAを試した

[docs/ota.md](../ota.md) の実装（PR#10、マージ済み）を受けて、実機device 2で
最初のUSB書き込みとOTA push本体を試した。

## やったこと・分かったこと

1. **`tools/devices.json`（実ファイル）に既存デバイス2台の `ota_password` を追記した。**
   スキーマ変更で新しく必須にしたフィールドなので、既存デバイスは追記しないと
   `provision_device.py` の `validate()` が「項目が足りない」で落ちる状態だった。
2. `secrets-h --id 2 --force` で `firmware/src/secrets.h` を再生成し、
   `pio run -e adxl355 -t upload` でUSB書き込み。**成功。**
3. 起動ログを確認（手動でDTR/RTSをトグルしてリセットし直し、流れる前に取得）:
   ```
   [boot] NamazuHaUrokoGaNai
   [sensor] ADXL355 ready
   [wifi] 10.255.255.157
   [uploader] spill files on boot: 0
   [ota] ready as namazu-2.local
   ```
   クラウド側 `/devices` API でも `online: true`、受信再開を確認した。
4. **push OTA本体（母艦から `espota` で焼く）を試したが、母艦から届かなかった。**
   - 母艦Mac（Claude Codeのbashが動く環境）の `en0` は `10.8.30.0/24`
   - device 2は `unnamed_network_g`（`10.255.255.0/24`）
   - `ping 10.255.255.1`（device 2のゲートウェイ）は通る（ttl=63、1ホップ挟んで
     ルーティングされている）
   - `namazu-2.local` のmDNS解決は失敗（`Host namazu-2.local Not Found`）
   - IP直指定（`--upload-port 10.255.255.157`）でも `espota` のUDP招待
     （ポート3232）に**無応答**（`No response from the ESP`、90秒超待って失敗）

## 何が決まったか

**push OTAが届かないのはファーム実装の不具合ではなく、ネットワーク側の制約。**
device側のOTAサーバは起動ログで稼働を確認済み。ICMPは通るのにUDP往復が通らない
挙動は、SSID名の `_g`（ゲスト回線と思われる命名）が示すとおり、**VLAN間の
クライアント分離**が疑わしい（デバイスの発信＝AWSへのHTTPS送信は素通りだが、
他ホストからの着信は塞がれる構成）。

`docs/ota.md` §5に落とし穴として記録し、§6の未着手を「push転送そのものの実機確認」
に更新した。HTTPSプル型（デバイス発信の経路）ならこの制約を受けないという設計上の
利点も追記した。

## 次に何が可能になったか

- push OTAを試すには、`unnamed_network_g` に実際に接続した端末（スマホ・同SSID上の
  PCなど）から `espota` を叩く必要がある。次回訪問時にそちらで試す。
- ルータ/APの `unnamed_network_g` 設定でクライアント分離を確認する選択肢もある
  （分離を外せばpushが素直に使えるようになる可能性がある）。
