"""地震候補スキャンLambda(docs/auto_judge.md)。

気象庁の地震一覧(list.json)を日次で見て、事後解析すべき候補をSlackへ知らせる。
**判定・保存はしない**——機械がやるのは「候補への気付き」まで。解析・判定・保存は
従来どおり人間(とセッション上のやり取り)がdocs/post_hoc_detection.mdの手順で行う。

重複排除は「広めの窓＋ステートフル」。日次実行ぴったりの窓だと実行時刻のブレで
境界の候補を取りこぼす恐れがあり、取りこぼしの方が実害が大きいので窓は実行間隔
より広めに取り、二重通知はDynamoDBの通知済みeid集合(common.quake_scan)で防ぐ。
"""

from __future__ import annotations

import datetime as dt
import os
import time

from batch_uplink import notify
from detection_range import CSV_PATH, FAR_BUT_NOTABLE_MAG, load_events, fit_good, worth_notifying
from scan_quakes import fetch_list, build_candidates, format_candidate
from station import DEFAULT_STATION

from common import quake_scan

JST = dt.timezone(dt.timedelta(hours=9))

# 実行間隔(24時間)より広めに取り、Lambdaの遅延・リトライで境界の候補を
# 取りこぼさないようにする（docs/auto_judge.md「重複排除」）。
WINDOW_HOURS = float(os.environ.get("NAMZ_QUAKE_SCAN_WINDOW_HOURS", "28"))

SATURDAY = 5  # datetime.weekday(): Monday=0 ... Sunday=6

# 候補が0件でない時は見逃されたら困るのでメンションを付ける
# （watchdogの欠測通知と同じ考え方・同じ宛先）。
SLACK_MENTION = "<@U0323ESK6> "


def _threshold_reminder() -> str:
    # 数字は実行時の値を埋め込む（本文のハードコードによる値のズレを避ける）。
    # 失敗検知のしきい値はwatchdog側の環境変数でこの関数からは見えないので、
    # 値までは埋め込まず置き場だけ示す。
    return (
        "そろそろ閾値を見直してもいいかも"
        f"（「遠すぎ」の通知閾値は今M≥{FAR_BUT_NOTABLE_MAG:g}"
        "(tools/detection_range.pyのFAR_BUT_NOTABLE_MAG)、"
        f"重複排除の窓は今{WINDOW_HOURS:g}時間(NAMZ_QUAKE_SCAN_WINDOW_HOURS)、"
        "失敗検知のしきい値はwatchdog側のNAMZ_QUAKE_SCAN_STUCK_AFTER_S。"
        "いずれもn=6の実例に基づく暫定値。tools/detection_events.csvに"
        "実例が増えていないか確認せよ）。"
    )


def handler(event, context):
    now = dt.datetime.now(JST)
    now_us = int(time.time() * 1e6)

    station = DEFAULT_STATION
    a, b = fit_good(load_events(CSV_PATH, station))
    since = now - dt.timedelta(hours=WINDOW_HOURS)

    entries = fetch_list()
    candidates = build_candidates(entries, station, a, b, since)
    wanted = [c for c in candidates if worth_notifying(c.zone, c.magnitude)]

    notified = quake_scan.get_notified_eids([c.eid for c in wanted])
    new_eids = set(quake_scan.filter_new([c.eid for c in wanted], notified))
    new_candidates = [c for c in wanted if c.eid in new_eids]

    if new_candidates:
        title = f"地震候補スキャン（{len(new_candidates)}件）"
        body = (
            f"{SLACK_MENTION}事後解析すべき候補が{len(new_candidates)}件。\n\n"
            + "\n\n".join(format_candidate(c, a, b) for c in new_candidates)
        )
    else:
        title = "地震候補スキャン"
        body = "新規候補なし。"

    if now.weekday() == SATURDAY:
        body += f"\n\n{_threshold_reminder()}"

    notify.from_env().notify(title, body, {})

    if new_candidates:
        quake_scan.mark_notified([c.eid for c in new_candidates], now_us)
    quake_scan.mark_success(now_us)

    return {"ok": True, "new": len(new_candidates)}
