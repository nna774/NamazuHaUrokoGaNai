"""events/<id>/ への波形バックフィルを一箇所に集約する。

detect Lambda（生バッチ到着のたび、速い経路）と watchdog Lambda（定期起動、ingestが
止まっても効く保険）の両方から同じロジックを呼べるようにするための切り出し。

`_confirm()`（detect側、STA/LTA再評価で閾値超過が続く間だけ再発火）と違い、ここでの
バックフィル判定は「onsetからPOST_SECONDS秒経ったか」という時間経過だけが条件で、
揺れの継続とは無関係——揺れが先に収まって`_confirm`の再発火が止まっても、後から
時間経過で必ず一度は全区間コピーが走るようにするための独立した経路。

以前は`waveform_prefix`の有無で「後追いコピー済みか」を判定していたが、確定検知
(`cloud_confirmed`)イベントは最初の`_confirm`呼び出しで即座に`waveform_prefix`が
立つため、この後追いが永久にスキップされていた（2026-09-17の茨城県南部M4.8の
事後解析で発覚、docs/log/2026-09-17-event-post-window-backfill-mechanism-fix.md）。
専用の`waveform_backfilled`フラグに切り替えて区別する。
"""

from __future__ import annotations

import json

from jismo.rounding import intensity_scale

from . import events, s3util, store

# イベント波形として保存する範囲（onset を基準に前後）。3.11のように振幅が閾値を
# 上回ったまま長く続くケースの取りこぼしを避けるため、1回あたりの窓自体を安全
# マージンとして大きめに取っている（2026-08-23、M5.9の事後解析でコーダが+190秒
# 近くまで残ると分かったのを受けて90→600に引き上げた。
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


def merge_meta(prev: dict | None, onset_us: int, max_intensity: float,
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


def get_prev_meta(s3, bucket: str, eid: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=bucket, Key=s3util.event_meta_key(eid))
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def put_meta(s3, bucket: str, eid: str, device_id: int, onset_us: int,
             max_intensity: float, peak_gal: float, a0: float | None = None) -> None:
    onset_us, max_intensity, peak_gal, a0 = merge_meta(
        get_prev_meta(s3, bucket, eid), onset_us, max_intensity, peak_gal, a0)
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
    s3.put_object(Bucket=bucket, Key=s3util.event_meta_key(eid),
                  Body=json.dumps(meta, ensure_ascii=False).encode(),
                  ContentType="application/json")


def copy_event_waveforms(s3, bucket: str, eid: str, onset_us: int, device_id: int) -> int:
    """onset 周辺の raw バッチを events/<id>/ へコピー（永久保存）。コピー数を返す。

    device_id で絞るのは必須。events/ は永久保存なので、別デバイスを混ぜると
    後始末が高くつく。
    """
    start_us = int(onset_us - PRE_SECONDS * 1e6)
    end_us = int(onset_us + POST_SECONDS * 1e6)
    return store.copy_raw_to_event(s3, bucket, eid, start_us, end_us, device_id)


def needs_backfill(item: dict, now_start_us: int) -> bool:
    """後追いの全区間コピーがまだ必要かどうかの純粋な判定（S3/DynamoDBを叩かない
    部分を切り出し、ユニットテストできるようにする）。

    - `manual`（`promote_event.py`が自前で範囲を決める）は対象外
    - `device_prompt`か`cloud_confirmed`のどちらかが立っているセッションだけが対象
    - `waveform_backfilled`が既に立っていれば一度きりで終わり
    - onsetから`POST_SECONDS`経っていなければまだ早い
    - onsetが1時間より古ければ諦める（通常は数十秒〜数分で片付くはずなので、
      それでも残っているのは異常系。無限に古いイベントを毎回scanし続けない）
    """
    if item.get("manual") or item.get("waveform_backfilled"):
        return False
    if not (item.get("device_prompt") or item.get("cloud_confirmed")):
        return False
    onset = int(item.get("onset_us", 0))
    if now_start_us < onset + int(POST_SECONDS * 1e6):
        return False
    if onset < now_start_us - 3_600_000_000:
        return False
    return True


def backfill_pending_events(s3, bucket: str, now_start_us: int) -> None:
    """onset+POST_SECONDS を過ぎたのに全区間コピーが済んでいないイベントを埋める。

    detect Lambda からは生バッチ到着のたび（`_process`内、揺れの有無を問わず毎回）、
    watchdog Lambda からは定期起動のたび呼ばれる想定。前者は速いが「次のバッチが
    届くこと」に依存し、後者は遅い(最大でスケジュール間隔ぶん)がingestの状況に
    依存しない——同じ判定を両方から回すことで、片方が機能しなくてももう片方が拾う。
    """
    for item in events.recent_events(200):
        if not needs_backfill(item, now_start_us):
            continue
        eid = item["event_id"]
        device_id = int(item.get("device_id", 0))
        onset = int(item["onset_us"])
        if copy_event_waveforms(s3, bucket, eid, onset, device_id) == 0:
            continue
        put_meta(s3, bucket, eid, device_id, onset,
                 float(item.get("max_intensity", 0)), float(item.get("peak_gal", 0)))
        events.set_waveform_prefix(eid, f"{s3util.EVENTS_PREFIX}/{eid}/")
        events.set_field(eid, "checked", True)
        events.set_field(eid, "waveform_backfilled", True)
