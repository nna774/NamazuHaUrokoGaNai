"""S3のraw batchをローカルにキャッシュするget_objectラッパー。

`tools/README.md`「何度も条件を変えて解析するときのS3キャッシュ」の方針を、都度
書き直さずに使えるよう1本化したもの。閾値やband・windowを変えながら
`detectlab.py`等で同じ区間を何度も読み直す解析で使う。

- **object keyをそのまま`.s3cache/`以下にミラーする**（`start_us`/`end_us`で丸ごと
  切った窓単位でキャッシュすると、窓をわずかにずらしただけで丸ごと引き直しになるため。
  バッチ(30秒粒度)単位でキャッシュすれば、窓が重なっている限り差分だけ取得すれば済む）。
- **`list_objects_v2`は常に本物のS3へ通す**（新着を見逃さないため。コストもほぼ無い）。
  キャッシュするのは`get_object`だけ。raw batchは書き込み後不変なので安全。
- **raw/とevents/は中身が同一バイト列のことがある**（`common.store.copy_raw_to_event`が
  検知時に`copy_object`でそのままコピーしたもの）。キーの末尾`<batch_start_us:020d>.bin`が
  一致していれば中身も一致するので、片方が未キャッシュでももう片方が既にキャッシュ済みなら
  そちらを流用してS3を叩かない（`detectlab.py`等で「rawを読んだ後にそのイベントだけ見たい」
  「eventを読んだ後に前後のrawが見たい」を行き来してもレイテンシが乗らないようにするため）。
  複数ヒットしたら安全側で諦めて素直にGETする。
- worktreeで作業していても、キャッシュ先はgit共通ディレクトリ（worktreeどうしで
  共有される）の親=メインチェックアウトを指す。worktreeごとに別ディレクトリになって
  キャッシュが効かない、という事態を避ける。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

RAW_PREFIX = "raw"
EVENTS_PREFIX = "events"

# raw/YYYY/MM/DD/HH/<device>-<ts:020d>.bin と events/<eid>/<ts:020d>.bin に
# 共通する末尾（lambda/common/s3util.py の raw_key / event_batch_key と同じ書式）。
_SUFFIX_RE = re.compile(r"(\d{20}\.bin)$")


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
        hit = _cross_prefix_hit(Key)
        if hit is not None:
            body = hit.read_bytes()
        else:
            resp = self._s3.get_object(Bucket=Bucket, Key=Key)
            body = resp["Body"].read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return {"Body": _BytesBody(body)}


def _cross_prefix_hit(key: str) -> Path | None:
    """raw/⇔events/ の対になるキーが既にキャッシュ済みならそのローカルパスを返す。

    events/<eid>/<ts>.bin は raw/.../<device>-<ts>.bin をそのまま copy_object した
    バイト列なので、末尾の<ts:020d>.bin が一致すれば中身も一致する。ヒットが複数
    （同一マイクロ秒に複数デバイスがバッチを開始、原理上ほぼ起き得ない）なら
    どれが正しいか決められないので諦めて呼び出し元に本物のGETをさせる。
    """
    m = _SUFFIX_RE.search(key)
    if m is None:
        return None
    suffix = m.group(1)
    if key.startswith(f"{RAW_PREFIX}/"):
        candidates = list(CACHE_ROOT.glob(f"{EVENTS_PREFIX}/**/{suffix}"))
    elif key.startswith(f"{EVENTS_PREFIX}/"):
        candidates = list(CACHE_ROOT.glob(f"{RAW_PREFIX}/**/*-{suffix}"))
    else:
        return None
    return candidates[0] if len(candidates) == 1 else None


def cached_client(s3=None) -> CachedS3:
    """使い方: `s3 = s3cache.cached_client()` を`store.load_window`等にそのまま渡す。"""
    return CachedS3(s3)
