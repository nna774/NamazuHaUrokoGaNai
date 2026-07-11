"""通知層。Notifier インターフェイスで差し替え可能にする（初期実装は Slack）。"""

from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    def notify(self, title: str, text: str, fields: dict | None = None) -> None:
        ...


class NullNotifier(Notifier):
    def notify(self, title, text, fields=None):
        pass


class SlackNotifier(Notifier):
    """Slack Incoming Webhook。"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def notify(self, title, text, fields=None):
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]
        if fields:
            blocks.append({
                "type": "section",
                "fields": [{"type": "mrkdwn", "text": f"*{k}*\n{v}"} for k, v in fields.items()],
            })
        payload = json.dumps({"text": title, "blocks": blocks}).encode()
        req = urllib.request.Request(
            self.webhook_url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()


def event_field(eid: str) -> str:
    """イベントIDを、ダッシュボードの該当ページへの Slack mrkdwn リンクにする。
    NAMZ_DASHBOARD_URL 未設定ならID文字列のまま返す。"""
    base = os.environ.get("NAMZ_DASHBOARD_URL", "").rstrip("/")
    return f"<{base}/#event/{eid}|{eid}>" if base else eid


def from_env() -> Notifier:
    """環境変数から Notifier を構築。将来 Discord 等を足すならここに分岐を追加。"""
    kind = os.environ.get("NAMZ_NOTIFIER", "slack").lower()
    if kind == "slack":
        url = os.environ.get("NAMZ_SLACK_WEBHOOK_URL")
        return SlackNotifier(url) if url else NullNotifier()
    return NullNotifier()
