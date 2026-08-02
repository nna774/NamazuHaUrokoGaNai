"""boto3 のリージョン解決を揃える。

このプロジェクトの手順書は一貫して `AWS_REGION=ap-northeast-1` と書いている
（CLAUDE.md・terraform/README.md）が、**boto3 が見るのは `AWS_DEFAULT_REGION`** で、
`AWS_REGION` だけ設定しても `NoRegionError` で落ちる。手順書どおりに叩いたのに
動かないという最悪の踏み方をするので、ツール側で吸収する。

優先順位: 既存の AWS_DEFAULT_REGION > AWS_REGION > aws CLI の設定 > 既定値。
"""

from __future__ import annotations

import os

DEFAULT_REGION = "ap-northeast-1"  # terraform の variable "region" と同じ


def ensure_region(default: str = DEFAULT_REGION) -> str:
    """boto3 が使うリージョンを確定させ、その値を返す。

    boto3 のクライアントを作る前に呼ぶこと。既に AWS_DEFAULT_REGION が
    設定されていれば触らない（プロファイルや ~/.aws/config も尊重される）。
    """
    region = os.environ.get("AWS_DEFAULT_REGION")
    if region:
        return region
    region = os.environ.get("AWS_REGION")
    if not region:
        # ~/.aws/config を見に行く。プロファイル指定にも追従する。
        try:
            import botocore.session

            region = botocore.session.get_session().get_config_variable("region")
        except Exception:  # noqa: BLE001  botocore が無い/壊れていても既定へ倒す
            region = None
    region = region or default
    os.environ["AWS_DEFAULT_REGION"] = region
    return region
