"""detect Lambda: raw/ へのバッチ到着ごとに直近窓を再解析し、地震を確定検知する。

- S3 の ObjectCreated(raw/*) で起動
- 直近 WINDOW_SECONDS 秒を連結して計測震度を再計算
- 閾値以上が継続する揺れがあれば:
    - イベント波形を events/<id>/ へコピー（永久保存）
    - DynamoDB に確定報を記録（デバイス速報と突合）
    - まだ確定通知していなければ Slack 通知（確定報）
"""

from __future__ import annotations

import os
from urllib.parse import unquote_plus

import boto3

from batch_uplink import notify

from common import detect_core, event_backfill, events, imagehost, quicklook, s3util, store, wire
from jismo.rounding import intensity_scale, scale_ordinal

s3 = boto3.client("s3")
BUCKET = os.environ["NAMZ_BUCKET"]

WINDOW_SECONDS = float(os.environ.get("NAMZ_DETECT_WINDOW_S", "120"))
THRESHOLD = float(os.environ.get("NAMZ_DETECT_THRESHOLD", "0.5"))
HOLD_SECONDS = float(os.environ.get("NAMZ_DETECT_HOLD_S", "0.3"))
# 窓の再評価をこの秒数の刻みまで間引く（0 = バッチ到着ごとに毎回評価する従来動作）。
# バッチ長を短くすると「起動回数」と「1回に読むオブジェクト数」が両方増え、S3 GET が
# 長さの二乗で効く。刻みを転送の都合から切り離すための設定。
STRIDE_SECONDS = detect_core.clamp_stride(
    float(os.environ.get("NAMZ_DETECT_STRIDE_S", "0")), WINDOW_SECONDS)
# 確定報を Slack 通知する最小計測震度(l)。速報の閾値(k)より低くする想定。
NOTIFY_CONFIRM_MIN = float(os.environ.get("NAMZ_NOTIFY_CONFIRM_MIN", "1.5"))
# イベント波形の保存範囲(PRE_SECONDS/POST_SECONDS)・後追いバックフィルは
# common/event_backfill.py に集約している（detect Lambdaとwatchdog Lambdaの
# 両方から同じロジックを呼ぶため）。


def handler(event, context):
    for rec in event.get("Records", []):
        key = unquote_plus(rec["s3"]["object"]["key"])
        if not key.startswith(f"{s3util.RAW_PREFIX}/"):
            continue
        try:
            _process(key)
        except Exception as e:  # noqa: BLE001
            print(f"detect error on {key}: {e!r}")


def _process(key: str):
    b = store.get_batch(s3, BUCKET, key)
    if not wire.is_calibrated(b.meta.sensor_type):
        # 非校正の生値センサ(ピエゾ等)はgal前提の震度計算に掛けられない
        # (docs/wire_format.md「sensor_type の帯域」)。
        return
    batch_len_us = int(b.meta.sample_count / b.meta.sample_rate_hz * 1e6)
    end_us = b.meta.batch_start_us + batch_len_us

    # 窓の読み直し(LIST+GET)は重いので、stride の境界を跨いだバッチだけが担当する。
    if detect_core.crosses_stride(b.meta.batch_start_us, end_us, STRIDE_SECONDS):
        # 窓は必ず1デバイスぶんに絞る。混ぜると継ぎ目の段差で震度が跳ねる。
        gal, win_start, fs = store.load_window(s3, BUCKET, end_us, WINDOW_SECONDS,
                                               b.meta.device_id)
        if gal.shape[0] > 0:
            det = detect_core.analyze(gal, fs, win_start, THRESHOLD, HOLD_SECONDS)
            if det is not None:
                _confirm(b.meta.device_id, det)

    # 確定検知・後追いバックフィルの有無に関わらず、速報イベントの波形も永久保存する。
    # stride で間引くのは窓の再評価だけ。こちらは S3 GET を伴わないので毎バッチ回す
    # （watchdog Lambda からも定期起動のたび同じ関数を呼ぶ。ingestが止まっても
    # 効く保険——common/event_backfill.py のモジュールdocstring参照）。
    event_backfill.backfill_pending_events(s3, BUCKET, b.meta.batch_start_us)


def _confirm(device_id: int, det: detect_core.Detection):
    """持続的な揺れ = クラウド確定報。波形保存 + DynamoDB + 通知。"""
    # 先にセッションへ記録して確定した event_id を得る（マージ後のidを使う）。
    eid, _ = events.record_cloud_detection(
        device_id, det.onset_us, det.max_intensity, det.peak_gal)
    prefix = f"{s3util.EVENTS_PREFIX}/{eid}/"
    event_backfill.copy_event_waveforms(s3, BUCKET, eid, det.onset_us, device_id)
    event_backfill.put_meta(s3, BUCKET, eid, device_id, det.onset_us,
                            det.max_intensity, det.peak_gal, det.a0)
    events.set_waveform_prefix(eid, prefix)

    # 通知はセッションの確定震度(FFT)が「新しい上位クラス」に達し、かつ l 以上の時。
    # 弱く始まって強くなるイベントでも、クラスが上がるたびに追従通知する。
    item = events.get_event(eid) or {}
    ci = float(item.get("confirmed_intensity", det.max_intensity))
    ord_now = scale_ordinal(ci)
    ord_prev = int(item.get("notified_confirm_ord", -1))
    if ci >= NOTIFY_CONFIRM_MIN and ord_now > ord_prev:
        scale = intensity_scale(ci)
        image_url = _quicklook_url(eid, ci, det.onset_us)
        notify.from_env().notify(
            f"地震を検知（確定報） 震度{scale}",
            f"クラウド解析で計測震度 *{ci:.1f}* （震度{scale}）を確定。",
            {"ピーク加速度": f"{det.peak_gal:.2f} gal", "イベント": notify.event_field(eid)},
            image_url=image_url,
            image_alt=f"波形 {eid}",
        )
        events.set_field(eid, "notified_confirm_ord", ord_now)


def _quicklook_url(eid: str, ci: float, onset_us: int) -> str | None:
    """保存済みイベント波形(events/<id>/)を読み直して PNG 化し、外部ホストへ上げて
    公開URLを返す。quicklook 側で静穏区間を落として揺れにズームするので、通知時点で
    onset 後が数秒しか溜まっていなくても手前の平坦部に潰されず読める。
    画像化・配信のどこかで失敗しても通知本体は止めない（テキストのみで飛ばす）。"""
    try:
        gal, win_start, fs = store.load_event(s3, BUCKET, eid, near_us=onset_us)
        if gal.shape[0] == 0:
            return None
        png = quicklook.render_png(gal, fs, win_start, onset_us)
        # desc に生URLを入れておくと Gyazo のページからイベント詳細へ飛べる。
        # ダッシュボードURL未設定なら、せめてどのイベントか分かるよう event_id を残す。
        desc = f"計測震度 {ci:.1f}\n{notify.event_url(eid) or eid}"
        return imagehost.upload_png(png, title=f"namazu {eid}", desc=desc)
    except Exception as e:  # noqa: BLE001
        print(f"quicklook failed for {eid}: {e!r}")
        return None
