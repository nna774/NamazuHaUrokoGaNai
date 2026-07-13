"""イベントの DynamoDB 管理。

デバイス速報とクラウド確定報を同一イベントに突合し、さらに**セッション方式**で
連続する揺れを1イベントにマージする。新しい onset が直近イベントの活動から
MERGE_GAP_US 以内なら、新規作成せずそのイベントを延長する（物理的な onset 時刻で
判定するので、後から走る detect も同じセッションに合流する）。
"""

from __future__ import annotations

import os
from decimal import Decimal

import boto3

# 新規セッションの event_id を作る際の時刻粒度[us]（読みやすさのため）。
BUCKET_US = 30_000_000  # 30秒
# 直近イベントの活動終端から onset がこの時間[us]以内なら同一セッションに延長する。
MERGE_GAP_US = 60_000_000  # 60秒

_table_cache = None


def _table():
    global _table_cache
    if _table_cache is None:
        _table_cache = boto3.resource("dynamodb").Table(os.environ["NAMZ_EVENTS_TABLE"])
    return _table_cache


def event_id(device_id: int, onset_us: int) -> str:
    """新規セッションの event_id（デバイス-30秒バケット）。"""
    return f"{device_id:04d}-{onset_us // BUCKET_US:d}"


def _latest_event(device_id: int) -> dict | None:
    """このデバイスの最新イベント（last_us が最大のもの）。単一デバイス想定の簡易 scan。"""
    items = [i for i in _table().scan(Limit=1000).get("Items", [])
             if int(i.get("device_id", -1)) == device_id]
    if not items:
        return None
    return max(items, key=lambda x: int(x.get("last_us", x.get("onset_us", 0))))


def _assign(device_id: int, onset_us: int) -> str:
    """onset を既存セッションに合流させるか、新規セッションの id を返す。"""
    latest = _latest_event(device_id)
    if latest:
        o = int(latest.get("onset_us", 0))
        last = int(latest.get("last_us", o))
        if o - MERGE_GAP_US <= onset_us <= last + MERGE_GAP_US:
            return latest["event_id"]  # 同一セッションに延長
    return event_id(device_id, onset_us)  # 新規セッション


def effective_intensity(item: dict) -> float:
    """表示に使う計測震度。確定済みならFFTの confirmed_intensity、
    未確定なら速報を含む max_intensity。一覧・詳細で同じ値を使うための単一ルール。"""
    if item.get("cloud_confirmed") and item.get("confirmed_intensity") is not None:
        return float(item["confirmed_intensity"])
    return float(item.get("max_intensity", 0))


def _record(device_id, onset_us, intensity, peak_gal,
            device_prompt=False, cloud_confirmed=False, waveform_prefix=None,
            confirmed_intensity=None):
    """イベントを作成/延長（get→merge→put）。(event_id, 直前のitem or None) を返す。

    単一デバイス・低頻度運用では並行更新はまず起きないため、条件付き更新でなく
    素直な read-modify-write にしている。
    """
    eid = _assign(device_id, onset_us)
    tbl = _table()
    prev = tbl.get_item(Key={"event_id": eid}).get("Item")

    item = prev or {
        "event_id": eid,
        "onset_us": Decimal(str(onset_us)),
        "last_us": Decimal(str(onset_us)),
        "device_id": device_id,
        "max_intensity": Decimal("0"),
        "peak_gal": Decimal("0"),
        "device_prompt": False,
        "cloud_confirmed": False,
    }
    item["device_id"] = device_id
    # onset はセッションの最初、last_us は最新の活動時刻
    item["onset_us"] = min(Decimal(str(onset_us)), Decimal(str(item.get("onset_us", onset_us))))
    item["last_us"] = max(Decimal(str(onset_us)), Decimal(str(item.get("last_us", onset_us))))
    item["max_intensity"] = max(Decimal(str(intensity)), Decimal(str(item.get("max_intensity", 0))))
    item["peak_gal"] = max(Decimal(str(peak_gal)), Decimal(str(item.get("peak_gal", 0))))
    if device_prompt:
        item["device_prompt"] = True
    if cloud_confirmed:
        item["cloud_confirmed"] = True
    if waveform_prefix is not None:
        item["waveform_prefix"] = waveform_prefix
    if confirmed_intensity is not None:
        # クラウドFFTの権威値。セッション内の最大を保持。
        item["confirmed_intensity"] = max(
            Decimal(str(confirmed_intensity)),
            Decimal(str(item.get("confirmed_intensity", 0))))

    tbl.put_item(Item=item)
    return eid, prev


def record_device_prompt(device_id, onset_us, intensity, peak_gal):
    """デバイス速報を記録。(event_id, is_new_session) を返す。"""
    eid, prev = _record(device_id, onset_us, intensity, peak_gal, device_prompt=True)
    return eid, prev is None


def record_cloud_detection(device_id, onset_us, intensity, peak_gal, waveform_prefix=None):
    """クラウド確定報を記録。(event_id, newly_confirmed) を返す。intensityはFFTの権威値。"""
    eid, prev = _record(device_id, onset_us, intensity, peak_gal,
                        cloud_confirmed=True, waveform_prefix=waveform_prefix,
                        confirmed_intensity=intensity)
    newly_confirmed = not (prev and prev.get("cloud_confirmed"))
    return eid, newly_confirmed


def get_event(eid: str) -> dict | None:
    return _table().get_item(Key={"event_id": eid}).get("Item")


def set_field(eid: str, name: str, value) -> None:
    """任意フィールドを1つ更新する（通知済みクラスの記録など）。"""
    _table().update_item(
        Key={"event_id": eid},
        UpdateExpression="SET #n = :v",
        ExpressionAttributeNames={"#n": name},
        ExpressionAttributeValues={":v": value},
    )


def set_artificial(eid: str, value: bool = True) -> None:
    """人工地震（テスト等で意図的/事故的に揺らしたもの）フラグを立てる/降ろす。

    立てると一覧の既定では隠れ（全件表示でのみ出る）、詳細で「人工地震(テスト等)」
    と表示される。確定/未確定は変えない（震度などの値はそのまま残す）。
    """
    set_field(eid, "artificial", bool(value))


def set_waveform_prefix(eid: str, prefix: str) -> None:
    """波形を events/ へ保存したことを記録（フラグは変えない）。"""
    _table().update_item(
        Key={"event_id": eid},
        UpdateExpression="SET waveform_prefix = :wp",
        ExpressionAttributeValues={":wp": prefix},
    )


def recent_events(limit: int = 50) -> list[dict]:
    """最近のイベントを新しい順で返す（単一デバイス想定の簡易 scan）。"""
    items = _table().scan(Limit=1000).get("Items", [])
    items.sort(key=lambda x: int(x.get("onset_us", 0)), reverse=True)
    return items[:limit]


def _scan_all() -> list[dict]:
    """テーブル全件を scan（ページネーション込み）。"""
    out: list[dict] = []
    kwargs: dict = {}
    while True:
        resp = _table().scan(**kwargs)
        out.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return out


def list_page(page: int = 0, size: int = 20, show_all: bool = False) -> tuple[list[dict], int]:
    """新しい順に並べた page ページ目(0始まり)の size 件と、（フィルタ後の）総件数を返す。

    show_all=False（既定）では「確定済み or 未評価(pending)」だけ出し、detectが評価して
    確定しなかったイベント（速報は来たが地震でなかった = checked かつ未確定）と、
    人工地震（artificial）としてフラグ付けしたものを隠す。

    件数が数千規模までは全件 scan+ソートで十分。それ以上に育ったら
    時刻レンジGSIでの本格ページングに移行する。
    """
    items = _scan_all()
    if not show_all:
        items = [it for it in items
                 if (it.get("cloud_confirmed") or not it.get("checked"))
                 and not it.get("artificial")]
    items.sort(key=lambda x: int(x.get("onset_us", 0)), reverse=True)
    start = max(0, page) * size
    return items[start:start + size], len(items)
