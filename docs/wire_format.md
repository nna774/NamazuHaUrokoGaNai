# バッチ ワイヤフォーマット v2

ESP32 → ingest Lambda に送るバイナリ。リトルエンディアン。

```
[ヘッダ 32B][サンプル列 N*3*幅][トレイラー(TLV, 可変・省略可)]
```

- **v1**: ヘッダ + サンプル列
- **v2**: 後ろに TLV トレイラーが付き**うる**。付かないバッチも v2 として正しい

## ヘッダ (32 bytes, packed)

| offset | type   | field           | 説明 |
|--------|--------|-----------------|------|
| 0      | u32    | magic           | `0x4E414D5A` (`"NAMZ"`) |
| 4      | u8     | version         | `1` = トレイラー無し / `2` = 付きうる |
| 5      | u8     | sensor_type     | 0=IIS3DHHC, 1=ADXL355, 2=LSM6DSO, ... |
| 6      | u8     | sample_format   | 0=int16, 1=int32（将来20bitセンサ用） |
| 7      | u8     | axes            | `3` |
| 8      | u64    | batch_start_us  | バッチ先頭サンプルの UNIX時刻 [µs] |
| 16     | u32    | sample_rate_mhz | サンプルレート [milli-Hz]（100Hz→100000） |
| 20     | u32    | sample_count    | サンプル数 N |
| 24     | f32    | scale_mg_per_lsb| 1 LSB あたりの mg（milli-g） |
| 28     | u32    | device_id       | デバイス識別子 |

## ペイロード

`sample_format` が int16 なら `int16_t data[N][3]`（x,y,z の順）、int32 なら `int32_t data[N][3]`。
サンプル `i` の時刻は `batch_start_us + round(i * 1e9 / sample_rate_mhz)` [µs]。

物理量への変換: `accel_mg = raw_lsb * scale_mg_per_lsb`。
gal (cm/s²) へは `accel_gal = accel_mg * 0.980665`。

## トレイラー (v2〜・省略可)

サンプル列の直後から末尾まで、TLV を並べる。1件は:

| type   | field   | 説明 |
|--------|---------|------|
| u16    | type    | 項目の種別 |
| u16    | len     | value のバイト長 |
| u8[len]| value   | 中身 |

**種別はセンサに紐付けない。** 「`sensor_type` が ADXL355 だから温度がある」ではなく
「温度の TLV があれば温度がある」と読む。センサの素性と容器の形は別の話であり、
前者に後者を従わせるとパーサが全機種の癖を知らないと読めなくなる。

読み手は**知らない `type` を `len` ぶん読み飛ばして次へ進む**。だから項目を足しても
古い読み手は壊れない。トレイラーの有無・長さは
`len(payload) - sample_count * 3 * 幅` から判る。

| type | 名前 | value | 説明 |
|------|------|-------|------|
| 1 | `sensor_temp` | u16 | センサ内蔵温度の**生値**。バッチ先頭時点の1点 |

温度を生値のまま送るのは、℃への換算定数をファームに焼くと、間違っていた時に
全機再書き込みになるため。換算は `lambda/common/wire.py` の `adxl355_temp_c()` で行う。
ADXL355 の温度は部品ごとのばらつきが大きく**絶対値は当てにならない**。
ドリフトとの相関を見る用途（相対変化）にのみ使うこと。

1点で足りるのは、追いたい架台の熱ドリフトが分〜時間の時定数で動くため。
30秒に1点でもナイキストに十分な余裕がある。

### 互換性

- トレイラーが付いても**古い読み手は壊れない**。サンプル列の長さは
  `sample_count` から決まるので、余剰バイトは読まれずに捨てられる。
- したがってファームを先に v2 にしてもクラウド側の事故は起きない。
- HMAC は body 全体に掛かるのでトレイラーも署名対象になる。

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
