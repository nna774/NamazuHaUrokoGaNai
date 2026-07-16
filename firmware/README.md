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

```bash
cp src/secrets.h.example src/secrets.h   # WiFi・エンドポイント・HMAC鍵を記入
```

## ビルド・書き込み

```bash
# 通常（送信あり）
pio run -t upload && pio device monitor

# Phase1: センサ検証のみ（WiFi/送信なし、シリアルにt_us,x,y,z）
pio run -e sensortest -t upload
python ../tools/capture_serial.py --port /dev/tty.usbserial-XXXX --seconds 60 > cap.csv
python ../tools/backtest.py cap.csv
```

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
- HMAC鍵はデバイスとingest Lambdaで共有。デバイスごとに変えるなら device_id で引く。
