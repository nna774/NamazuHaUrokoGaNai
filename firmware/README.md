# firmware — ESP32 地震計ファームウェア

ESP32-D0WDQ6 (WROOM-32 系) + IIS3DHHC。PlatformIO / Arduino core。

## タスク構成

| task | core | 役割 |
|------|------|------|
| `sampling` | 1 | esp_timerで100Hz起床 → SPI読み → バッチ蓄積 → リアルタイム震度 → 検知 |
| `uploader` | 0 | バッチのHTTPS POST / NTP / リトライ・バックフィル / WiFi再接続 |

測定と送信を別コアに分けているので、送信でブロックしても測定は止まらない。

## ライブラリ (`lib/`)

| lib | 内容 |
|-----|------|
| `AccelSensor` | センサ抽象インターフェイス（差し替え可能に） |
| `Iis3dhhc`    | IIS3DHHC SPIドライバ（レジスタ直叩き） |
| `Adxl355`     | ADXL355 SPIドライバ（`-DNAMZ_SENSOR_ADXL355` で選択。[docs/adxl355.md](../docs/adxl355.md)） |
| `Shindo`      | リアルタイム計測震度（FIR。`tools/jismo/realtime.py` の写経） |
| `Batch`       | ワイヤフォーマットのエンコード |
| `Uploader`    | 送信キュー・LittleFS退避・リトライ・HMAC署名 |
| `TimeSync`    | NTP(smooth同期) |
| `Display`     | 内蔵TFTへの表示（震度階級・ステート・WiFi等） |

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

`secrets.h` は手で書かず `tools/provision_device.py` で払い出す（`tools/devices.json` が
単一の真実。詳細は [docs/design.md](../docs/design.md)）。

```bash
python ../tools/provision_device.py secrets-h --id 2 --force
```

## ビルド・書き込み

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
