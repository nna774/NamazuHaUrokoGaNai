# バッチ ワイヤフォーマット v1

ESP32 → ingest Lambda に送るバイナリ。リトルエンディアン。

## ヘッダ (32 bytes, packed)

| offset | type   | field           | 説明 |
|--------|--------|-----------------|------|
| 0      | u32    | magic           | `0x4E414D5A` (`"NAMZ"`) |
| 4      | u8     | version         | `1` |
| 5      | u8     | sensor_type     | 0=IIS3DHHC, 1=ADXL355, 2=LSM6DSO, ... |
| 6      | u8     | sample_format   | 0=int16, 1=int32（将来20bitセンサ用） |
| 7      | u8     | axes            | `3` |
| 8      | u64    | batch_start_us  | バッチ先頭サンプルの UNIX時刻 [µs] |
| 16     | u32    | sample_rate_mhz | サンプルレート [milli-Hz]（100Hz→100000） |
| 20     | u32    | sample_count    | サンプル数 N |
| 24     | f32    | scale_mg_per_lsb| 1 LSB あたりの mg（milli-g） |
| 28     | u32    | device_id       | デバイス識別子 |

## ペイロード

`sample_format` が int16 なら `int16_t data[N][3]`（x,y,z の順）。
サンプル `i` の時刻は `batch_start_us + round(i * 1e9 / sample_rate_mhz)` [µs]。

物理量への変換: `accel_mg = raw_lsb * scale_mg_per_lsb`。
gal (cm/s²) へは `accel_gal = accel_mg * 0.980665`。

## 認証

HTTP ヘッダ `X-Namz-Signature: hex(HMAC_SHA256(secret, body))` を付ける。
`X-Namz-Device: <device_id>` も付与し、ingest 側で device_id→secret を引く。

## アラート（デバイス速報）

検知タスクが即時に投げる軽量 JSON。バッチとは別エンドポイント/別パス。

```json
{
  "device_id": 1,
  "detected_at_us": 1720000000000000,
  "realtime_intensity": 2.3,
  "peak_gal": 12.4,
  "kind": "device_prompt"
}
```
