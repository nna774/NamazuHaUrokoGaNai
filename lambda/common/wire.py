"""バッチのバイナリ形式のパース。docs/wire_format.md / firmware WireFormat.h と一致。

v1 = ヘッダ + サンプル列。v2 = その後ろに TLV トレイラーが付きうる。
トレイラーは無くても v2 として正しい。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = 0x4E414D5A
HEADER_FMT = "<IBBBBQIIfI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MG_TO_GAL = 0.980665

assert HEADER_SIZE == 32, HEADER_SIZE

# --- トレイラー種別（firmware WireFormat.h の TrailerType と一致させる）---
TLV_HEADER_FMT = "<HH"
TLV_HEADER_SIZE = struct.calcsize(TLV_HEADER_FMT)
TRAILER_SENSOR_TEMP = 1

# sensor_type（firmware AccelSensor::sensorType() と一致させる）。
# 温度の換算式はチップ依存なので、どのチップかの判定に使う（TLVのtypeとは無関係）。
SENSOR_TYPE_IIS3DHHC = 0
SENSOR_TYPE_ADXL355 = 1

# 表示用の名前。ダッシュボードのデバイス詳細ページで使う。
SENSOR_TYPE_NAMES = {
    SENSOR_TYPE_IIS3DHHC: "IIS3DHHC",
    SENSOR_TYPE_ADXL355: "ADXL355",
}

# ADXL355 の内蔵温度の換算（データシートの公称値）。
#   温度[℃] = 25 + (raw - TEMP_AT_25C) / LSB_PER_DEGC
# 公称値であって校正値ではない。部品ごとのばらつきがあるので**絶対値は当てにならない**。
# ドリフトとの相関を見る用途（相対変化）にのみ使うこと。ファームは生値のまま送る。
#
# 1885 は ADXL355 の値。**1852 は ADXL359 のもので、混同しやすい**
# （ADI のデモコード ADuCM360_demo_adxl355_pmdz は 1852 を使っており誤り）。
# 出典: Linux drivers/iio/accel/adxl355_core.c の adxl35x_chip_info[]。
# ADXL355 = 1885 / ADXL359 = 1852 とチップ別に書き分けられている。
ADXL355_TEMP_AT_25C = 1885.0
ADXL355_TEMP_LSB_PER_DEGC = -9.05


def adxl355_temp_c(raw: int) -> float:
    """ADXL355 の温度生値を℃へ。絶対精度は無い（上のコメント参照）。"""
    return 25.0 + (raw - ADXL355_TEMP_AT_25C) / ADXL355_TEMP_LSB_PER_DEGC


def temp_c_for(sensor_type: int, raw: int | None) -> float | None:
    """(sensor_type, 生値) から℃へ。換算式が無いセンサ種別や生値が無ければ None。

    `common.device_temp` に記録した DynamoDB アイテムのように、BatchMeta を経由
    しない場所（既に raw/sensor_type だけが手元にある場所）から呼ぶための実体。
    """
    if raw is None or sensor_type != SENSOR_TYPE_ADXL355:
        return None
    return adxl355_temp_c(raw)


def temp_c(meta: BatchMeta) -> float | None:
    """バッチの温度トレイラーを℃へ。換算式が無いセンサ種別や温度自体が無ければ None。"""
    return temp_c_for(meta.sensor_type, meta.sensor_temp_raw)


@dataclass
class BatchMeta:
    version: int
    sensor_type: int
    sample_format: int
    axes: int
    batch_start_us: int
    sample_rate_hz: float
    sample_count: int
    scale_mg_per_lsb: float
    device_id: int
    # TLV トレイラー。{type: payload}。未知の type もそのまま持つ。
    trailer: dict[int, bytes] = field(default_factory=dict)

    @property
    def sensor_temp_raw(self) -> int | None:
        """センサ内蔵温度の生値（バッチ先頭時点）。無ければ None。"""
        v = self.trailer.get(TRAILER_SENSOR_TEMP)
        return struct.unpack("<H", v)[0] if v and len(v) >= 2 else None


@dataclass
class Batch:
    meta: BatchMeta
    raw: np.ndarray   # shape (N, 3) int
    gal: np.ndarray   # shape (N, 3) float [gal]

    def timestamps_us(self) -> np.ndarray:
        n = self.meta.sample_count
        dt_us = 1e6 / self.meta.sample_rate_hz
        return self.meta.batch_start_us + np.round(np.arange(n) * dt_us).astype(np.int64)


def parse(data: bytes) -> Batch:
    if len(data) < HEADER_SIZE:
        raise ValueError("too short for header")
    (magic, version, sensor_type, sample_format, axes, start_us,
     rate_mhz, count, scale, device_id) = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic:#x}")
    if axes != 3:
        raise ValueError(f"unexpected axes {axes}")

    meta = BatchMeta(
        version=version, sensor_type=sensor_type, sample_format=sample_format,
        axes=axes, batch_start_us=start_us, sample_rate_hz=rate_mhz / 1000.0,
        sample_count=count, scale_mg_per_lsb=scale, device_id=device_id,
    )

    payload = data[HEADER_SIZE:]
    if sample_format == 0:
        dtype = np.dtype("<i2")
    elif sample_format == 1:
        dtype = np.dtype("<i4")
    else:
        raise ValueError(f"unknown sample_format {sample_format}")

    need = count * 3 * dtype.itemsize
    if len(payload) < need:
        raise ValueError(f"payload short: {len(payload)} < {need}")
    raw = np.frombuffer(payload[:need], dtype=dtype).reshape(count, 3).astype(np.int64)
    gal = raw.astype(float) * scale * MG_TO_GAL
    meta.trailer = parse_trailer(payload[need:])
    return Batch(meta=meta, raw=raw, gal=gal)


def parse_trailer(data: bytes) -> dict[int, bytes]:
    """TLV 列を {type: payload} にする。

    壊れていても例外にしない。トレイラーは補助情報であって、これを理由に
    波形1バッチを丸ごと捨てるのは割に合わない。読める分だけ返す。
    """
    out: dict[int, bytes] = {}
    pos = 0
    while pos + TLV_HEADER_SIZE <= len(data):
        typ, length = struct.unpack(TLV_HEADER_FMT, data[pos:pos + TLV_HEADER_SIZE])
        pos += TLV_HEADER_SIZE
        if pos + length > len(data):
            break  # 途中で切れている
        out[typ] = data[pos:pos + length]
        pos += length
    return out
