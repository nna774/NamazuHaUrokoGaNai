# OTA更新 作戦（未実装）

ファームの無線更新。2026-08-03 時点で**未着手**（[STATUS.md](STATUS.md) の残タスク）。
コードのどこにも `ArduinoOTA` / `esp_https_ota` は無い。着手する時に一から調べ直さずに
済むよう、土台の棚卸しと選択肢・落とし穴をまとめておく。

## 1. 土台の棚卸し（既に整っているもの）

| 項目 | 状態 |
|------|------|
| パーティション | `esp32dev` 既定の `default.csv` → `app0`/`app1` 各 0x140000 (1.25MB) + `otadata`。**最初からOTA可能な構成** |
| 現ファームのサイズ | `firmware.bin` 約 1,025KB（esp32dev / adxl355 ともほぼ同じ）。スロットの **78%**、余裕 約280KB |
| LittleFS | `spiffs` 0x160000 (1.4MB) は app とは別領域。OTAしても `/spill` の退避バッチは消えない |
| 失敗の検知 | watchdog Lambda の欠測通知（既定300秒）が**そのまま安全網になる**。焼き損ねてブートループすればSlackが鳴る |

`platformio.ini` に `board_build.partitions` の指定は無く、ボード既定をそのまま使っている。

## 2. 選択肢

### A. ArduinoOTA（LAN内からpush）

母艦から `espota` で投げる。`platformio.ini` に env を1つ足すだけで経路ができる。

```ini
[env:esp32dev-ota]
extends = env:esp32dev
upload_protocol = espota
upload_port = 192.168.x.x        ; or namazu-2.local
upload_flags = --auth=<password>
```

デバイス側は送信タスク（Core0）で `ArduinoOTA.begin()` / `handle()` を回す。測定タスク
（Core1・優先度10）を巻き込まない側に置くのが要点。

**工数の見積り: 半日以下。** 実装の大半は §3 の停止シーケンスであって、OTA自体ではない。

### B. HTTPSプル型（`esp_https_ota` / `HTTPUpdate`）

S3/CloudFront にバージョンマニフェストと `firmware-<env>-<ver>.bin` を置き、デバイスが
起動時と定期にポーリングして落とす。外出先からでも更新でき、無人運用に耐える。既に
HTTPS + HMAC で喋っている経路があるので、マニフェストの署名にデバイス鍵を流用できる。

**工数の見積り: 2〜3日。** 内訳はデバイス側のポーリングと検証、マニフェスト生成と
S3配置（terraform + `tools/` のCLI）、バージョン管理の取り決め。

### 推奨

**A を先に入れて、B は必要になってから。** 現状2台しかなく両方LAN内にあるので、
いきなり配信基盤を作るのは過剰。据え付け先が離れて物理アクセスが面倒になった時点が
B の潮時。

## 3. 実装時の落とし穴（このプロジェクト固有）

- **フラッシュ書き込み中はキャッシュが無効になり、flash 実行のタスクが止まる。**
  100Hz の `esp_timer` は確実に取りこぼす。OTA開始前に**測定を止め、`Uploader` の
  RAMキューを LittleFS へ退避してから**始めること。しないと再起動でRAM上のバッチが
  消え、「2xxが返るまでバッチを捨てない」という `Uploader` の不変条件を自分で破る
  （`kMaxRamBatches` は 3〜6 バッチ = 最大3分ぶん）。
- **ロールバックは期待しない。** Arduino core の既定ビルドは
  `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` が入っておらず、新イメージは書けた時点で
  有効扱いになる。自動で前のスロットへ戻ることはない。最後の砦は物理アクセス。
- **パーティションテーブル自体はOTAで変えられない。** app スロットを広げたくなった時
  （`min_spiffs` 等への変更）はUSBで焼き直しになる。余裕が280KBしかないことを考えると、
  **USBが楽なうちにレイアウトを決めておく**のが安い。
- **env が機種ごとに違う**（IIS3DHHC機は `esp32dev`、ADXL355機は `adxl355`）。配布物は
  env 別に分ける。env は `python tools/provision_device.py env --id N` で引ける。
- **正常なOTAなら欠測通知は鳴らない。** 1MBの転送は数十秒、閾値は300秒。逆に鳴ったら
  本当に失敗しているということ。

## 4. 着手時に決めること

- OTAパスワード（A）／マニフェスト署名鍵（B）をどこに置くか。`tools/devices.json` を
  単一の真実とする既存の払い出し経路（`provision_device.py`）に乗せるのが素直。
- 測定停止・退避・更新・再起動のシーケンスをどのタスクが駆動するか。
- B をやる場合、更新の指示をどう伝えるか（定期ポーリング / ingest のレスポンスヘッダに
  目標バージョンを載せる、など）。
