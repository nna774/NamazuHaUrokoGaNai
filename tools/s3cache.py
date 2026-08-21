"""S3のraw batchをローカルにキャッシュするget_objectラッパー。

`tools/README.md`「何度も条件を変えて解析するときのS3キャッシュ」の方針を、都度
書き直さずに使えるよう1本化したもの。閾値やband・windowを変えながら
`detectlab.py`等で同じ区間を何度も読み直す解析で使う。

- **object keyをそのまま`.s3cache/`以下にミラーする**（`start_us`/`end_us`で丸ごと
  切った窓単位でキャッシュすると、窓をわずかにずらしただけで丸ごと引き直しになるため。
  バッチ(30秒粒度)単位でキャッシュすれば、窓が重なっている限り差分だけ取得すれば済む）。
- **`list_objects_v2`は常に本物のS3へ通す**（新着を見逃さないため。コストもほぼ無い）。
  キャッシュするのは`get_object`だけ。raw batchは書き込み後不変なので安全。
- worktreeで作業していても、キャッシュ先はgit共通ディレクトリ（worktreeどうしで
  共有される）の親=メインチェックアウトを指す。worktreeごとに別ディレクトリになって
  キャッシュが効かない、という事態を避ける。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _main_checkout_root() -> Path:
    here = Path(__file__).resolve().parent
    common_dir = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"], cwd=here,
    ).decode().strip()
    return (here / common_dir).resolve().parent


CACHE_ROOT = _main_checkout_root() / ".s3cache"


class _BytesBody:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class CachedS3:
    """boto3 S3クライアントの`get_object`だけをローカルキャッシュする薄いラッパー。

    `common.store.load_window`/`load_event`等、`list_objects_v2`/`get_object`しか
    使わない箇所にそのまま渡せる。
    """

    def __init__(self, s3=None):
        if s3 is None:
            import boto3
            s3 = boto3.client("s3")
        self._s3 = s3

    def list_objects_v2(self, **kwargs):
        return self._s3.list_objects_v2(**kwargs)

    def get_object(self, Bucket, Key):  # noqa: N803
        path = CACHE_ROOT / Key
        if path.exists():
            return {"Body": _BytesBody(path.read_bytes())}
        resp = self._s3.get_object(Bucket=Bucket, Key=Key)
        body = resp["Body"].read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return {"Body": _BytesBody(body)}


def cached_client(s3=None) -> CachedS3:
    """使い方: `s3 = s3cache.cached_client()` を`store.load_window`等にそのまま渡す。"""
    return CachedS3(s3)
