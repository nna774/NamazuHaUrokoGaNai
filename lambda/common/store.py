"""S3 の raw/ からバッチを読み、時間窓を組み立てる。"""

from __future__ import annotations

import numpy as np

from . import s3util, wire


def get_batch(s3, bucket: str, key: str) -> wire.Batch:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return wire.parse(obj["Body"].read())


def list_raw_keys_in_range(s3, bucket: str, start_us: int, end_us: int) -> list[str]:
    """[start,end] と重なる raw/ のキーを時系列順で返す。"""
    keys: list[str] = []
    for prefix in s3util.raw_hour_prefixes(start_us, end_us):
        token = None
        while True:
            kw = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kw)
            for it in resp.get("Contents", []):
                keys.append(it["Key"])
            if resp.get("IsTruncated"):
                token = resp["NextContinuationToken"]
            else:
                break
    # キー末尾の startus(20桁ゼロ埋め) で時系列ソート
    keys.sort()
    return keys


def load_window(s3, bucket: str, end_us: int, seconds: float) -> tuple[np.ndarray, int, float]:
    """end_us を終端とする直近 `seconds` 秒の波形を連結して返す。

    returns: (gal[N,3], window_start_us, fs)。データが無ければ (empty, end_us, 100.0)。
    """
    start_us = int(end_us - seconds * 1e6)
    keys = list_raw_keys_in_range(s3, bucket, start_us - 60_000_000, end_us)
    parts = []
    win_start = None
    fs = 100.0
    for key in keys:
        try:
            b = get_batch(s3, bucket, key)
        except Exception:
            continue
        b_start = b.meta.batch_start_us
        b_end = b_start + int(b.meta.sample_count / b.meta.sample_rate_hz * 1e6)
        if b_end < start_us or b_start > end_us:
            continue
        fs = b.meta.sample_rate_hz
        if win_start is None:
            win_start = b_start
        parts.append(b.gal)
    if not parts:
        return np.empty((0, 3)), end_us, fs
    return np.concatenate(parts, axis=0), win_start, fs
