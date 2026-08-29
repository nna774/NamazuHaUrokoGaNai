"""detect Lambda: raw/ へのバッチ到着ごとに直近窓を再解析し、地震を確定検知する。

- S3 の ObjectCreated(raw/*) で起動
- 直近 WINDOW_SECONDS 秒を連結して計測震度を再計算
- 閾値以上が継続する揺れがあれば:
    - イベント波形を events/<id>/ へコピー（永久保存）
    - DynamoDB に確定報を記録（デバイス速報と突合）
    - まだ確定通知していなければ Slack 通知（確定報）
"""

from __future__ import annotations

import json
import os
from urllib.parse import unquote_plus

import boto3

from batch_uplink import notify

from common import detect_core, events, imagehost, quicklook, s3util, store, wire
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
# イベント波形として保存する範囲（onset を基準に前後）。揺れが続く限り _confirm が
# stride ごとに再発火し、そのたびにこの幅で追加コピーされるので実質的には伸びるが、
# 1回あたりの窓自体も安全マージンとして大きめに取っておく（3.11のように振幅が閾値を
# 上回ったまま長く続くケースの取りこぼしを避けるため。2026-08-23、M5.9の事後解析で
# コーダが+190秒近くまで残ると分かったのを受けて90→600に引き上げた。
# docs/log/2026-08-23-event-post-window-extension.md）。
# PRE_SECONDSはonset基準の安全マージンであって、detectlab.pyが背景比較に使う
# 「発生時刻基準-150〜-30秒」の背景RMS推定窓を狙ったものではない。onsetは常に
# 「発生時刻+伝播時間」より後に来るため、30秒では伝播時間が30秒を超える地震
# （震源距離が数十km以上ある大半のケース）で保存開始点が発生時刻より後ろに
# なってしまい、rawの保持期限(90日)を過ぎた後は事後解析で背景に一切届かなく
# なる。手動昇格のデフォルト(--pre 180)に揃え、保存範囲そのものに背景ぶんを
# 焼き込む（2026-08-30千葉県東方沖M4.9の事後解析で発覚、
# docs/log/2026-08-30-chiba-oki-m4.9-post-hoc-detection.md参照）。
PRE_SECONDS = 180
POST_SECONDS = 600


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

    # 確定検知の有無に関わらず、速報イベントの波形も永久保存する。stride で間引くのは
    # 窓の再評価だけ。こちらは S3 GET を伴わないので毎バッチ回す。
    _preserve_prompt_waveforms(b.meta.batch_start_us)


def _confirm(device_id: int, det: detect_core.Detection):
    """持続的な揺れ = クラウド確定報。波形保存 + DynamoDB + 通知。"""
    # 先にセッションへ記録して確定した event_id を得る（マージ後のidを使う）。
    eid, _ = events.record_cloud_detection(
        device_id, det.onset_us, det.max_intensity, det.peak_gal)
    prefix = f"{s3util.EVENTS_PREFIX}/{eid}/"
    _copy_event_waveforms(eid, det.onset_us, device_id)
    _put_meta(eid, device_id, det.onset_us, det.max_intensity, det.peak_gal, det.a0)
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


def _preserve_prompt_waveforms(now_start_us: int):
    """デバイス速報で拾われたイベントの波形を events/ へ永久保存し、評価済みにする。

    後続(POST_SECONDS)ぶんのバッチが出揃った頃に一度だけ処理する。この時点で
    確定(cloud_confirmed)していなければ「速報は来たが地震でなかった」= 評価済み未確定
    なので checked=true を立てる（一覧の既定では隠れる）。
    """
    for item in events.recent_events(200):
        if not item.get("device_prompt") or item.get("waveform_prefix"):
            continue
        onset = int(item.get("onset_us", 0))
        if now_start_us < onset + int(POST_SECONDS * 1e6):
            continue  # まだ後続バッチが揃っていない
        if onset < now_start_us - 3_600_000_000:
            continue  # 1時間より古い未保存の速報は諦める(通常は数十秒で保存される)
        eid = item["event_id"]
        device_id = int(item.get("device_id", 0))
        if _copy_event_waveforms(eid, onset, device_id) == 0:
            continue
        _put_meta(eid, device_id, onset,
                  float(item.get("max_intensity", 0)), float(item.get("peak_gal", 0)))
        events.set_waveform_prefix(eid, f"{s3util.EVENTS_PREFIX}/{eid}/")
        events.set_field(eid, "checked", True)  # detect評価済み（未確定なら既定で隠す）


def _copy_event_waveforms(eid: str, onset_us: int, device_id: int) -> int:
    """onset 周辺の raw バッチを events/<id>/ へコピー（永久保存）。コピー数を返す。

    device_id で絞るのは必須。events/ は永久保存なので、別デバイスを混ぜると
    後始末が高くつく。
    """
    start_us = int(onset_us - PRE_SECONDS * 1e6)
    end_us = int(onset_us + POST_SECONDS * 1e6)
    copied = 0
    for key in store.list_raw_keys_in_range(s3, BUCKET, start_us, end_us, device_id):
        # ファイル名末尾の startus で範囲判定
        try:
            b_start = int(key.rsplit("-", 1)[1].split(".")[0])
        except (IndexError, ValueError):
            continue
        if b_start < start_us - 30_000_000 or b_start > end_us:
            continue
        dst = s3util.event_batch_key(eid, b_start)
        s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": key}, Key=dst)
        copied += 1
    return copied


def _merge_meta(prev: dict | None, onset_us: int, max_intensity: float,
                peak_gal: float, a0: float | None) -> tuple[int, float, float, float | None]:
    """既存 meta.json があれば、弱い再発火が強い記録を消さないよう最大値へマージする。

    onset_us はセッションの真の起点なので最小値、震度・加速度は最大値を残す
    （events.py の `_record` と同じ「最大/最小を保持」方針を S3 側にも合わせる）。
    """
    if prev is None:
        return onset_us, max_intensity, peak_gal, a0
    onset_us = min(onset_us, int(prev.get("onset_us", onset_us)))
    max_intensity = max(max_intensity, float(prev.get("max_intensity", 0)))
    peak_gal = max(peak_gal, float(prev.get("peak_gal", 0)))
    prev_a0 = prev.get("a0_gal")
    if prev_a0 is not None:
        a0 = max(a0, float(prev_a0)) if a0 is not None else float(prev_a0)
    return onset_us, max_intensity, peak_gal, a0


def _get_prev_meta(eid: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=s3util.event_meta_key(eid))
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def _put_meta(eid: str, device_id: int, onset_us: int,
              max_intensity: float, peak_gal: float, a0: float | None = None):
    onset_us, max_intensity, peak_gal, a0 = _merge_meta(
        _get_prev_meta(eid), onset_us, max_intensity, peak_gal, a0)
    meta = {
        "event_id": eid,
        "device_id": device_id,
        "onset_us": onset_us,
        "max_intensity": max_intensity,
        "scale": intensity_scale(max_intensity),
        "peak_gal": peak_gal,
    }
    if a0 is not None:
        meta["a0_gal"] = a0
    s3.put_object(Bucket=BUCKET, Key=s3util.event_meta_key(eid),
                  Body=json.dumps(meta, ensure_ascii=False).encode(),
                  ContentType="application/json")
