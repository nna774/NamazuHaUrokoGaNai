"""S3 の raw/ からバッチを読み、時間窓を組み立てる。"""

from __future__ import annotations

import numpy as np

from . import s3util, wire


def get_batch(s3, bucket: str, key: str) -> wire.Batch:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return wire.parse(obj["Body"].read())


def _key_batch_start_us(key: str) -> int | None:
    """raw/.../<device>-<startus>.bin から startus を取り出す（GETせずに窓判定するため）。"""
    try:
        return int(key.rsplit("-", 1)[1].split(".")[0])
    except (IndexError, ValueError):
        return None


# バッチ長の上限見積り（ファーム側 kBatchSeconds は最大30秒）。GET前フィルタで
# 「この時刻に始まったバッチはどんなに長くても window に届かない」を判定する余裕。
MAX_BATCH_DURATION_US = 60_000_000

# バッチ間の正常な送信ジッタの上限目安（実測で~0.1-0.4秒）。これを超える空きは
# WiFi再接続等でサンプリング自体が数十秒単位で止まっていた実欠落とみなす。
BATCH_GAP_TOLERANCE_US = 2_000_000


def list_raw_keys_in_range(s3, bucket: str, start_us: int, end_us: int,
                           device_id: int | None = None) -> list[str]:
    """[start,end] と重なる raw/ のキーを時系列順で返す。

    **device_id を渡さないと全デバイスのキーが混ざる。** キーは
    `raw/.../<device>-<startus>.bin` なので、sort() ではデバイス番号が先に効き、
    時系列に見えて実は「1号機の全部→2号機の全部」の順に並ぶ。これを波形として
    連結すると継ぎ目に巨大な段差ができ、震度が跳ねる（実際に踏んだ）。
    波形を組み立てる用途では必ず device_id を指定すること。
    """
    keys: list[str] = []
    dev = f"{device_id:04d}-" if device_id is not None else ""
    for prefix in s3util.raw_hour_prefixes(start_us, end_us):
        token = None
        while True:
            kw = {"Bucket": bucket, "Prefix": prefix + dev}
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


def _split_into_contiguous_segments(
    batches: list[wire.Batch],
) -> tuple[list[tuple[np.ndarray, int]], float]:
    """バッチ列を時系列連結しつつ、`BATCH_GAP_TOLERANCE_US` を超える実欠落
    （WiFi再接続等でサンプリング自体が止まっていた区間）で分割する。

    単純に全部連結すると、欠落後のサンプルの時刻が `win_start + i/fs` で
    実時刻より欠落秒数ぶん早く計算され、onset時刻等が実際より早くズレる
    （2026-08-29 NERV防災通知の事後解析で発見。docs/log/2026-08-29-gunma-kitabu-m3.2
    -post-hoc-detection.md参照）。どの区間を残すかは呼び出し側の用途で異なる
    （`load_window`は末尾＝直近が欲しい、`load_event`は肝心のonsetを含む区間が
    欲しい——保存範囲に複数の欠落があると、onsetは先頭でも末尾でもない真ん中の
    区間に入ることがある。実際に踏んだ）ので、ここでは分割だけ行い、選択は
    呼び出し側に委ねる。

    returns: ([(gal, segment_start_us), ...], fs)。segmentsは時系列順。
    """
    segments: list[tuple[np.ndarray, int]] = []
    parts: list[np.ndarray] = []
    seg_start: int | None = None
    prev_end: int | None = None
    fs = 100.0
    for b in batches:
        b_start = b.meta.batch_start_us
        b_end = b_start + int(b.meta.sample_count / b.meta.sample_rate_hz * 1e6)
        if prev_end is not None and b_start - prev_end > BATCH_GAP_TOLERANCE_US:
            segments.append((np.concatenate(parts, axis=0), seg_start))
            parts = []
            seg_start = None
        fs = b.meta.sample_rate_hz
        if seg_start is None:
            seg_start = b_start
        parts.append(b.gal)
        prev_end = b_end
    if parts:
        segments.append((np.concatenate(parts, axis=0), seg_start))
    return segments, fs


def _pick_segment(
    segments: list[tuple[np.ndarray, int]], fs: float, near_us: int | None,
) -> tuple[np.ndarray, int]:
    """複数の連続区間から1つを選ぶ。`near_us`を含む区間があればそれ、
    無ければ最も近い区間。`near_us`未指定なら最大（サンプル数最多）の区間。"""
    if near_us is not None:
        for gal, start in segments:
            end = start + int(gal.shape[0] / fs * 1e6)
            if start <= near_us < end:
                return gal, start

        def distance(seg: tuple[np.ndarray, int]) -> int:
            gal, start = seg
            end = start + int(gal.shape[0] / fs * 1e6)
            return min(abs(start - near_us), abs(end - near_us))

        return min(segments, key=distance)
    return max(segments, key=lambda seg: seg[0].shape[0])


def load_event(s3, bucket: str, eid: str, near_us: int | None = None,
               ) -> tuple[np.ndarray, int, float]:
    """events/<id>/*.bin を時系列に連結して返す（永久保存したイベント波形）。

    returns: (gal[N,3], window_start_us, fs)。無ければ (empty, 0, 100.0)。
    api の _event と同じ読み方。detect のクイックルック描画で使う。

    保存範囲の中に実欠落（`BATCH_GAP_TOLERANCE_US`超）が複数あると、肝心の
    onsetは先頭でも末尾でもない真ん中の区間に入ることがある
    （2026-08-29、群馬県北部M3.2の事後解析で実際に踏んだ——post側で無関係な
    欠落がもう1回起きていた）。`near_us`（通常はonset_us）を渡せば、それを
    含む区間（無ければ最も近い区間）を選ぶ。渡さなければ最大の区間を選ぶ。
    """
    prefix = f"{s3util.EVENTS_PREFIX}/{eid}/"
    keys: list[str] = []
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        keys += [it["Key"] for it in resp.get("Contents", []) if it["Key"].endswith(".bin")]
        if resp.get("IsTruncated"):
            token = resp["NextContinuationToken"]
        else:
            break
    keys.sort()  # キー末尾の startus(20桁ゼロ埋め) で時系列順
    batches = []
    for key in keys:
        try:
            batches.append(get_batch(s3, bucket, key))
        except Exception:
            continue
    segments, fs = _split_into_contiguous_segments(batches)
    if not segments:
        return np.empty((0, 3)), 0, fs
    gal, win_start = _pick_segment(segments, fs, near_us)
    return gal, win_start, fs


def copy_raw_to_event(s3, bucket: str, eid: str, start_us: int, end_us: int,
                      device_id: int) -> int:
    """[start,end] と重なる raw バッチを events/<eid>/ へコピー（永久保存）。コピー数を返す。

    device_id は必須。混ぜると events/<eid>/ に別デバイスの波形が入り、
    `load_event` が同じ罠を踏む（イベントは永久保存なので後始末が高くつく）。
    """
    copied = 0
    for key in list_raw_keys_in_range(s3, bucket, start_us, end_us, device_id):
        b_start = _key_batch_start_us(key)  # ファイル名末尾の startus で範囲判定
        if b_start is None or b_start < start_us - 30_000_000 or b_start > end_us:
            continue
        s3.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": key},
                       Key=s3util.event_batch_key(eid, b_start))
        copied += 1
    return copied


def load_window(s3, bucket: str, end_us: int, seconds: float,
                device_id: int) -> tuple[np.ndarray, int, float]:
    """end_us を終端とする直近 `seconds` 秒の波形を1デバイスぶん連結して返す。

    device_id は必須。省略できるようにしておくと、多点化した時に別デバイスの波形を
    つなげて震度が跳ねる（`list_raw_keys_in_range` の注記を読め）。

    欠落（実欠落。`BATCH_GAP_TOLERANCE_US`超）があった場合は**末尾の連続区間**
    （＝ end_us に一番近い、直近の意味そのもの）だけを残す。

    returns: (gal[N,3], window_start_us, fs)。データが無ければ (empty, end_us, 100.0)。
    """
    start_us = int(end_us - seconds * 1e6)
    keys = list_raw_keys_in_range(s3, bucket, start_us - 60_000_000, end_us, device_id)
    batches = []
    fs = 100.0
    for key in keys:
        # list_raw_keys_in_range の Prefix は時間(hour)+device までしか絞れないので、
        # ここでは同じ時間帯の全バッチが渡ってくる。GETする前にファイル名の startus
        # だけで窓外を弾く（弾かずに全部GETしてから捨てると、その時間帯に溜まった
        # バッチ数だけリクエストの分数によらず一定時間かかる — 実際に踏んだ）。
        hint = _key_batch_start_us(key)
        if hint is not None and (hint > end_us or hint + MAX_BATCH_DURATION_US < start_us):
            continue
        try:
            b = get_batch(s3, bucket, key)
        except Exception:
            continue
        # プレフィックスで絞ってあるが中身でも確かめる。連結してよいのは同一デバイスだけ。
        if b.meta.device_id != device_id:
            continue
        b_start = b.meta.batch_start_us
        b_end = b_start + int(b.meta.sample_count / b.meta.sample_rate_hz * 1e6)
        if b_end < start_us or b_start > end_us:
            continue
        fs = b.meta.sample_rate_hz
        batches.append(b)
    segments, fs = _split_into_contiguous_segments(batches)
    if not segments:
        return np.empty((0, 3)), end_us, fs
    gal, win_start = segments[-1]
    return gal, win_start, fs
