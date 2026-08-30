# firmware — ESP32 地震計ファームウェア

ESP32-D0WDQ6 (WROOM-32 系) + IIS3DHHC。PlatformIO / Arduino core。

## タスク構成

| task | core | 役割 |
|------|------|------|
| `sampling` | 1 | esp_timerで100Hz起床 → SPI読み → バッチ蓄積 → リアルタイム震度 → 検知 |
| `uploader` | 0 | バッチのHTTPS POST / NTP / リトライ・バックフィル / WiFi再接続 / OTA更新の待ち受け |

測定と送信を別コアに分けているので、送信でブロックしても測定は止まらない。

## ライブラリ (`lib/`)

| lib | 内容 |
|-----|------|
| `AccelSensor` | センサ抽象インターフェイス（差し替え可能に） |
| `Iis3dhhc`    | IIS3DHHC SPIドライバ（レジスタ直叩き） |
| `Adxl355`     | ADXL355 SPIドライバ（`-DNAMZ_SENSOR_ADXL355` で選択。[docs/adxl355.md](../docs/adxl355.md)） |
| `Shindo`      | リアルタイム計測震度（FIR。`tools/jismo/realtime.py` の写経） |
| `NamzWire`    | NAMZ形式を `Batch` に載せる薄い層（32Bヘッダ・3軸サンプル・TLVトレイラー） |
| `Display`     | 内蔵TFTへの表示（震度階級・ステート・WiFi等） |

## 共有ライブラリ (`batch-uplink`)

`Batch`（送信バッファ）・`Uploader`（キュー/LittleFS退避/リトライ/HMAC署名）・
`TimeSync`（NTP）は地震計固有の知識を持たないので、
[batch-uplink](https://github.com/nna774/batch-uplink) に切り出して周波数モニタ
[Electabuzz](https://github.com/nna774/Electabuzz) と共有している。

`platformio.ini` の `lib_deps` で**タグを指して pin する**。`#master` にすると
向こうのために入れた変更がこちらの次回ビルドで黙って混入し、「何も変えていないのに
再ビルドで壊れる」という最悪の壊れ方をする。

ワイヤ形式（magic・ヘッダ・TLV）を知っているのは `NamzWire` だけ。この分離が
崩れていないことは `test/run.sh` が守る。

## テスト (`test/`)

`Batch`・`NamzWire` は Arduino に依存しないのでホストで走る。実機もPlatformIOも要らない。

```bash
firmware/test/run.sh
```

`test_batch_bytes.cpp` は **`Batch` を一般化する前の実装から採取した実出力**を golden に
持っている。送出バイト列が1バイトも変わっていないことを、焼かずに確かめるためのもの。

`lib/Shindo/JmaFirTaps.h` は生成物。係数を変えたら:

```bash
cd ../tools && python gen_fir_header.py
```

`lib/Display/ClassFont.h` も生成物（震度階級用の大型フォント。内蔵フォントに
大きな `+` が無いため、`0-9` `+` `-` `.` だけを DejaVu Sans Bold から起こしたもの）。
字種やサイズを変えたら:

```bash
# TTF: https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37
cd tools && ../../.venv/bin/python gen_class_font.py DejaVuSans-Bold.ttf > ../lib/Display/ClassFont.h
```

## セットアップ

デバイス識別情報・秘密・エンドポイントURLはコンパイル時定数(旧`secrets.h`)ではなく
NVSに持つ（[docs/ota.md](../docs/ota.md) §7「バイナリの秘密情報を分離しないと成立
しない」——pull型OTAでenvごとに1本のバイナリを公開URLへ置くと、コンパイル時に
焼き込んだ秘密がそのまま世界に漏れる）。`tools/provision_device.py`で払い出し
（`tools/devices.json` が単一の真実。詳細は [docs/design.md](../docs/design.md)）、
書き込み専用ビルドで焼いてNVSへ書く。

```bash
# NVSへ書く値を生成 → 書き込み専用ビルドで焼く（1回だけ）
python ../tools/provision_device.py provision-h --id 2 --force
pio run -e adxl355-provision -t upload --upload-port <USBポート>   # IIS3DHHC機は -e provision
```

## ビルド・書き込み

続けて通常のfirmwareを焼く（NVSはOTAをまたいで保持されるので以降は不要）。

```bash
# 通常（送信あり）
pio run -t upload && pio device monitor

# センサ別: IIS3DHHC機は esp32dev(既定)、ADXL355機は adxl355
pio run -e "$(python ../tools/provision_device.py env --id 2)" -t upload

# Phase1: センサ検証のみ（WiFi/送信なし、シリアルにt_us,x,y,z）
pio run -e sensortest -t upload            # ADXL355機は -e adxl355-sensortest
python ../tools/capture_serial.py --sensor iis3dhhc \
    --port /dev/tty.usbserial-XXXX --seconds 60 > cap.csv
python ../tools/backtest.py cap.csv
```

### OTA更新（USBを繋がず無線で焼く）

詳細は [docs/ota.md](../docs/ota.md)。HTTPSプル型（デバイスが自分で取得しにいく）。
`tools/publish_ota.sh`でビルド〜配布、`tools/request_ota.py`で更新を許可する。

```bash
../tools/publish_ota.sh "$(python ../tools/provision_device.py env --id 2)"
python ../tools/request_ota.py request 2 <version>
```

### 書き込めない時

**`Uploading ...` の直後で固まったら、ブートローダに落ちていない。**

このクローンボードの自動リセット回路（DTR/RTS でのブートローダ起動）は当てにならない。
とくに **`sensortest` 系が載っている時に再発する**。あれは 100Hz でシリアルへ CSV を
吐き続けるので、esptool の同期パケットと噛み合わない。喋らないファーム同士の
焼き替えでは起きないため、Phase1 のあと本番ファームを焼く場面で必ず踏む。

手でブートローダに落とす:

1. **GPIO0（左ボタン / BOOT）を押したまま** USB を抜く
2. 押したまま挿し直す（リセットボタンがある板なら EN を一度押すのでもよい）
3. **押したまま** `pio run -e <env> -t upload`
4. `Writing at 0x...` が流れたら離す

要は「起動の瞬間に GPIO0 が LOW」であればよい。リセットでも電源投入でも成立する。

それでも駄目なら:

```bash
lsof /dev/cu.usbserial-XXXX /dev/tty.usbserial-XXXX   # 他プロセスがポートを掴んでいないか
PLATFORMIO_UPLOAD_SPEED=115200 pio run -e <env> -t upload
```

`upload_speed` は一度 921600 で転んで 460800 に落としてある（`c667a20`）。
**書き始めてから**化けるなら速度、**書き始める前に**固まるならブートローダ側だ。
症状で切り分けろ。

## 配線

TTGO T-Display 系ボード（ESP32 + 内蔵ST7789 TFT）向けの割り当て。
既定の 18/19/23/5 は基板上のTFTが使っておりヘッダに出ていないため使えない。

| 信号 | ESP32 | IIS3DHHC |
|------|-------|----------|
| SCK  | GPIO25 | SPC |
| MISO | GPIO27 | SDO |
| MOSI | GPIO26 | SDI |
| CS   | GPIO33 | CS |
| VDD  | 3V3    | VDD |
| GND  | GND    | GND |

ピンは `src/config.h` で変更可。無印 WROOM-32 DevKit なら 18/19/23/5 に戻してよい。
（36/37/38/39 は入力専用なので SCK/MOSI/CS には使えない点に注意）

## 注意

- `postBatch` は現状 `setInsecure()` でTLS証明書を検証していない。運用前に
  Function URL のルート証明書をピン留めすること（`config.h` にTODO）。
- HMAC鍵はデバイスとingest Lambdaで共有。デバイスごとの鍵は
  `NAMZ_HMAC_SECRET_<id>`（terraform の `device_hmac_secrets`）で引く。
  **サーバ側を apply してから焼くこと**。逆順だと新しい鍵の署名を検証できず 401 になる。

## serial port

```bash
pio device monitor -b 115200
```

## クラッシュ後のcoredump吸い出し

**ESP-IDFのcoredump-to-flashが既定で有効・パーティションも確保済み**
（`partitions_16mb.csv`の`coredump`パーティション）。パニック（WDTリブート含む）が
起きると、その瞬間の全タスクのレジスタ・コールスタックがフラッシュへ自動で残る——
シリアルに張り付いてクラッシュの瞬間に立ち会う必要はなく、**後日USBを挿すだけで
過去に起きたクラッシュの中身を読める**（次に別のクラッシュが起きて上書きされるまで）。

読み出しにはシンボル解決用の`firmware.elf`が要る。OTAで配信した版なら
`tools/publish_ota.sh`が`.bin`と同時に本物の`.elf`もS3へ上げている
（`ota/<env>/<version>.elf`）ので、それをそのまま使う——手元での再ビルドは不要。
再ビルドしたelfは`esp_app_desc_t.app_elf_sha256`フィールド自体がビルドのたびに
違う値で焼き直されるため、実機のcoredumpとは原理的に一致しない
（コードがビット一致していてもSHA256照合には引っかかる）。本物のelfならこの
問題自体が起きない。

```bash
pip install esp-coredump   # .venv等へ

# 1. 実機のfw_versionに対応するelfをS3から取得する
aws s3 cp s3://namazu-dashboard-<account-id>/ota/<env>/<fw_version>.elf firmware.elf

# 2. 読み出し（parttool.py周りの回避が要る場合の詳細は下記ログ）
esp-coredump --chip esp32 --port <port> --baud 115200 info_corefile \
  --gdb <toolchain-xtensa-esp32-elf-gdb> --off 0xFF0000 \
  firmware.elf
```

OTAで一度も配信していない版（USB書き込みのみ、または`.elf`保存より前に配信した版）
だと`.elf`がS3に無い——その場合のみ、実機の`fw_version`と同じコミットで手元で
再ビルドし、S3の`.bin`とバイト比較して検証してから使う（差分は
`app_elf_sha256`フィールド自体と末尾チェックサムのみのはず。それ以外に差分が
あればビルド環境がズレているのでシンボル解決を信用してはいけない）。
初回は`esp-coredump`がESP-IDF本体（`parttool.py`）を前提にしていて素直には
動かなかった。回避手順・実例は
[docs/log/2026-08-29-device2-task-wdt-coredump-tls-handshake.md](../docs/log/2026-08-29-device2-task-wdt-coredump-tls-handshake.md)、
`.elf`保存に至った経緯は
[docs/log/2026-08-31-store-ota-elf-artifact.md](../docs/log/2026-08-31-store-ota-elf-artifact.md)。
