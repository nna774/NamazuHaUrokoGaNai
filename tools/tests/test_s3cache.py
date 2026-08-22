import s3cache


class _StubS3:
    """get_objectを呼んだかどうかだけ数える。呼ばれたら壊れたバイト列を返し、
    「本来キャッシュから取れるはずが誤ってS3へ通した」テストの失敗を分かりやすくする。"""

    def __init__(self):
        self.calls = []

    def get_object(self, Bucket, Key):  # noqa: N803
        self.calls.append(Key)
        return {"Body": _Body(b"from-s3")}


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


TS = "00000001700000000000"  # batch_start_us を020dで埋めたダミー値


def _raw_key(device: str = "0001") -> str:
    return f"raw/2026/08/23/09/{device}-{TS}.bin"


def _events_key(eid: str = "evt1") -> str:
    return f"events/{eid}/{TS}.bin"


def test_events_miss_reuses_already_cached_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(s3cache, "CACHE_ROOT", tmp_path)
    raw_path = tmp_path / _raw_key()
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"already-cached-raw-bytes")

    stub = _StubS3()
    client = s3cache.CachedS3(stub)
    body = client.get_object(Bucket="b", Key=_events_key())["Body"].read()

    assert body == b"already-cached-raw-bytes"
    assert stub.calls == []  # S3へは通っていない
    assert (tmp_path / _events_key()).read_bytes() == b"already-cached-raw-bytes"


def test_raw_miss_reuses_already_cached_event(tmp_path, monkeypatch):
    monkeypatch.setattr(s3cache, "CACHE_ROOT", tmp_path)
    event_path = tmp_path / _events_key()
    event_path.parent.mkdir(parents=True)
    event_path.write_bytes(b"already-cached-event-bytes")

    stub = _StubS3()
    client = s3cache.CachedS3(stub)
    body = client.get_object(Bucket="b", Key=_raw_key())["Body"].read()

    assert body == b"already-cached-event-bytes"
    assert stub.calls == []


def test_no_cross_prefix_hit_falls_back_to_s3(tmp_path, monkeypatch):
    monkeypatch.setattr(s3cache, "CACHE_ROOT", tmp_path)
    stub = _StubS3()
    client = s3cache.CachedS3(stub)

    body = client.get_object(Bucket="b", Key=_events_key())["Body"].read()

    assert body == b"from-s3"
    assert stub.calls == [_events_key()]


def test_ambiguous_cross_prefix_hit_falls_back_to_s3(tmp_path, monkeypatch):
    """同じ<ts>で複数デバイス分キャッシュされている(原理上ほぼ起き得ない)場合は
    どれが正しいか決められないので安全側でS3へ通す。"""
    monkeypatch.setattr(s3cache, "CACHE_ROOT", tmp_path)
    for device in ("0001", "0002"):
        p = tmp_path / _raw_key(device)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"raw-{device}".encode())

    stub = _StubS3()
    client = s3cache.CachedS3(stub)
    body = client.get_object(Bucket="b", Key=_events_key())["Body"].read()

    assert body == b"from-s3"
    assert stub.calls == [_events_key()]
