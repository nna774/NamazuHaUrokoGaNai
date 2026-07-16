"""画像配信層。PNG を公開URLに載せて Slack から参照できるようにする。

初期実装は Gyazo。Incoming Webhook はファイルアップロードできないので、いったん
外部ホストに上げて `https://i.gyazo.com/<hash>.png` の公開URLを得る戦略を取る。
S3公開やpresignedより設定が要らず、URLが永続する。将来 S3+CloudFront 等に
差し替えるならこのモジュールに分岐を足す。
"""

from __future__ import annotations

import json
import os
import urllib.request

GYAZO_UPLOAD_URL = "https://upload.gyazo.com/api/upload"


def _multipart(fields: dict[str, str], filename: str, filedata: bytes) -> tuple[bytes, str]:
    """multipart/form-data を手組みする（requests非依存）。(body, content_type) を返す。"""
    boundary = "----namazuboundary7c3f1a2b"
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="imagedata"; '
        f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode())
    parts.append(filedata)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_gyazo(png: bytes, token: str, *, title: str = "", desc: str = "",
                 filename: str = "namazu.png", timeout: float = 10) -> str | None:
    """PNG を Gyazo にアップロードし、直リンク(i.gyazo.com/<hash>.png)を返す。失敗時 None。"""
    fields = {"access_token": token}
    if title:
        fields["title"] = title
    if desc:
        fields["desc"] = desc
    body, content_type = _multipart(fields, filename, png)
    req = urllib.request.Request(
        GYAZO_UPLOAD_URL, data=body, headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data.get("url") or data.get("permalink_url")


def upload_png(png: bytes, *, title: str = "", desc: str = "") -> str | None:
    """環境変数から配信先を選んで PNG を上げ、公開URLを返す。設定が無ければ None。"""
    token = os.environ.get("NAMZ_GYAZO_TOKEN")
    if token:
        return upload_gyazo(png, token, title=title, desc=desc)
    return None
