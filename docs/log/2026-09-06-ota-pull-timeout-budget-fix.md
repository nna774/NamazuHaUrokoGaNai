# 2026-09-06 pull型OTA取得のタイムアウト予算を修正

## きっかけ

[同日のdevice1パッチ配信](2026-09-06-device1-hostbyname-patch-rollout.md)中、
`performPullOta()`が2026-08-31にdevice2で特定済みの既知バグ(WDTパニック)を
esp32dev環境でも踏んだ。ユーザーに「どうやって直すといい？」と聞かれ、方針を
検討してから実装した。

## 原因（再確認）

`WiFiClientSecure`は締切が2つ独立している:

- `socket_timeout`(接続の`select()`・全readの`SO_RCVTIMEO`) — 既定30秒
- `handshake_timeout`(TLSハンドシェイクの内部リトライループ) — 既定**120秒**

`performPullOta()`はどちらも設定しないまま`httpUpdate.update()`を呼んでおり、
`onProgress()`によるWDT給餌は「進捗があった時」にしか効かないため、接続・
ハンドシェイク・単発の読み取りのいずれかがWDT(20秒)より長く詰まると
`onProgress()`が一度も呼ばれないままハードパニックする。

## 方針

`performPullOta()`は`ret != HTTP_UPDATE_OK`で失敗を検知し
`resumeSamplingAfterOtaFailure`→60秒バックオフで再試行する**穏当な失敗パスを
既に持っている**。直すべきは「遅いネットワークがその失敗パスに届く前にWDTが
先に発火する」点だけなので、batch-uplinkの`Uploader`で既にやった対処
(接続・ハンドシェイク・レスポンスヘッダの3区間をいずれも3000msに縮める、
[design.md「ネットワークI/Oのタイムアウト予算」](../design.md)参照)と同じ
考え方をそのまま持ち込むことにした。

値はUploaderに揃えて4秒とした——OTAは1回きりの取得で頻度への感度が低く多少
緩めても実害は少ないが、実績のある値に揃える方を優先した(ユーザー承認)。

## 実装

`firmware/src/main.cpp`・`firmware/src/piezo_main.cpp`の両方の`performPullOta()`に
（`WiFiClientSecure`インスタンス生成後・`httpUpdate.update()`より前に）以下の2行を追加:

```cpp
client.setHandshakeTimeout(4);
client.setTimeout(4);
```

`esp32dev`・`adxl355`で`pio run`確認済み。`piezo`はこのマシン固有の環境問題
(riscv32ツールチェーンがx86_64専用バイナリのままでApple Siliconでは実行不可、
Rosetta未導入)でビルド自体が失敗したが、変更箇所は本線と一字一句同じパターンで
文法的には問題ない——ビルド確認は後日別途行う。

ビルド中に`firmware/certs/amazon_root_ca1.pem`へPlatformIOがNUL終端を追記し
`.piobkp`バックアップを残す仕様に気づいた(証明書埋め込みの副作用、今回の変更とは
無関係)。意図しない差分だったため`git checkout --`で戻し`.piobkp`は削除した——
`.gitignore`への追記は今回は見送り、気づいた事実だけ記録する。

## 次に何が可能になったこと

- OTA取得中の単発ネットワーク遅延はハードパニックではなく既存のバックオフ再試行に
  収まるようになった（実機でのOTA配信時の再起動回数低減を期待）
- `esp32dev`・`adxl355`への実機OTA配信・長期観察はまだ。`piezo`のビルド確認と、
  このマシンのriscv32ツールチェーン問題の解消も持ち越し
