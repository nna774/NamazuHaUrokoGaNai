"""watchdog Lambda: 定期起動し、各デバイスの最終受信からの経過を見て欠測を通知する。

不在（データが来ないこと）はイベント駆動では検知できないので、外から定期的に見る。
EventBridge の定期ルールで数分おきに起動し、ingest が更新する namazu-devices の
last_ingest_at_us を見る。

- NAMZ_OFFLINE_AFTER_S を超えて受信が途絶えたら「欠測」を Slack 通知。
- 落ちている間は NAMZ_OFFLINE_RENOTIFY_S 間隔で再送（既定1日）。
- 受信が再開したら「復帰」を1回通知して状態を解除。
- 受信は続いているが測定時刻が NAMZ_LAG_AFTER_S 以上遅れていたら「データ遅延」を通知。
  こちらも NAMZ_LAG_RENOTIFY_S 間隔で再送し、遅延が解消したら1回通知して解除。

状態遷移の判定は devices.evaluate()/evaluate_lag() に集約（DynamoDB 抜きでテストできる）。
"""

from __future__ import annotations

import datetime as dt
import os
import time

from common import devices, notify

# 生存とみなす最終受信からの猶予[s]。バッチは30秒間隔なので、既定300秒＝約10バッチ落ち。
OFFLINE_AFTER_S = float(os.environ.get("NAMZ_OFFLINE_AFTER_S", "300"))
# 落ちている間の再送間隔[s]。既定1日。
OFFLINE_RENOTIFY_S = float(os.environ.get("NAMZ_OFFLINE_RENOTIFY_S", "86400"))
# 受信は続くが測定時刻がこの秒数以上遅れたら「データ遅延」とみなす。既定600秒＝10分。
LAG_AFTER_S = float(os.environ.get("NAMZ_LAG_AFTER_S", "600"))
# 遅延が続いている間の再送間隔[s]。既定1日。
LAG_RENOTIFY_S = float(os.environ.get("NAMZ_LAG_RENOTIFY_S", "86400"))

JST = dt.timezone(dt.timedelta(hours=9))


def _humanize(seconds: float) -> str:
    s = int(seconds)
    if s < 90:
        return f"{s}秒"
    m = s // 60
    if m < 90:
        return f"{m}分"
    h = m // 60
    if h < 48:
        return f"{h}時間"
    return f"{h // 24}日"


def _fmt_time(us: int) -> str:
    if not us:
        return "（記録なし）"
    return dt.datetime.fromtimestamp(us / 1e6, JST).strftime("%Y-%m-%d %H:%M:%S JST")


def handler(event, context):
    now_us = int(time.time() * 1e6)
    offline_after = int(OFFLINE_AFTER_S * 1e6)
    renotify_after = int(OFFLINE_RENOTIFY_S * 1e6)
    lag_after = int(LAG_AFTER_S * 1e6)
    lag_renotify = int(LAG_RENOTIFY_S * 1e6)
    n = notify.from_env()
    actions = []

    for item in devices.list_devices():
        did = int(item.get("device_id", 0))
        last = int(item.get("last_ingest_at_us", 0))
        age = _humanize(devices.staleness_us(item, now_us) / 1e6)

        action = devices.evaluate(item, now_us, offline_after, renotify_after)
        if action is not None:
            actions.append({"device_id": did, "action": action})
            if action in ("offline", "offline_again"):
                title = "デバイス欠測" if action == "offline" else "デバイス欠測（継続）"
                n.notify(
                    title,
                    f"device *{did:04d}* から *{age}* データが来ていない。落ちているかもしれない。",
                    {"最終受信": _fmt_time(last), "経過": age},
                )
                devices.mark_offline_notified(did, now_us)
            elif action == "recovery":
                n.notify(
                    "デバイス復帰",
                    f"device *{did:04d}* がデータ送信を再開した。",
                    {"最終受信": _fmt_time(last)},
                )
                devices.clear_offline(did)

        # データ遅延（受信は続くが測定時刻が遅れている）。欠測中は evaluate_lag が黙る。
        lag_action = devices.evaluate_lag(item, now_us, lag_after, lag_renotify, offline_after)
        if lag_action is not None:
            actions.append({"device_id": did, "action": lag_action})
            last_batch = int(item.get("last_batch_start_us", 0))
            lag = _humanize((devices.lag_us(item, now_us) or 0) / 1e6)
            if lag_action in ("lag", "lag_again"):
                title = "データ遅延" if lag_action == "lag" else "データ遅延（継続）"
                n.notify(
                    title,
                    f"device *{did:04d}* のデータが *{lag}* 遅れている。"
                    "受信は続いているが測定時刻が追いついていない（時計ずれか追いつき中）。",
                    {"最新データ時刻": _fmt_time(last_batch), "遅延": lag},
                )
                devices.mark_lag_notified(did, now_us)
            elif lag_action == "lag_recovery":
                n.notify(
                    "データ遅延解消",
                    f"device *{did:04d}* のデータ遅延が解消した。",
                    {"最新データ時刻": _fmt_time(last_batch)},
                )
                devices.clear_lag(did)

    return {"ok": True, "actions": actions}
