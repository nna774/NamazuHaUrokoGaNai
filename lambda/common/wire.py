"""バッチのバイナリ形式 v1 のパース。docs/wire_format.md / firmware WireFormat.h と一致。"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAGIC = 0x4E414D5A
HEADER_FMT = "<IBBBBQIIfI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MG_TO_GAL = 0.980665

assert HEADER_SIZE == 32, HEADER_SIZE


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
    return Batch(meta=meta, raw=raw, gal=gal)
