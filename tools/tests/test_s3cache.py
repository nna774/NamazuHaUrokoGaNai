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
DEVICE = "0001"
# events.event_id()は f"{device_id:04d}-{bucket}" 書式。バケット番号はonset由来で
# batch自身のtsとは無関係に決まるので、テストでもtsとは違う値を使う。
EID = f"{DEVICE}-999"


def _raw_key(device: str = DEVICE) -> str:
    # _cross_prefix_hit はtsから日時を逆算してhourディレクトリを直接見に行くので、
    # テスト側もs3cache._raw_hour_dirで同じ計算をしてキーを組み立てる（決め打ちの
    # 日付だと逆算結果と噛み合わずキャッシュミス扱いになる）。
    return f"{s3cache._raw_hour_dir(TS)}/{device}-{TS}.bin"


def _events_key(eid: str = EID) -> str:
    return f"events/{eid}/{TS}.bin"


def test_events_miss_reuses_already_cached_raw(tmp_path, monkeypatch):
    """eidの先頭4桁(=device_id)からraw側の完全なキーを直接組み立てて拾える（探索不要）。"""
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
    """raw→events方向はeidのバケット番号が分からないのでglobで探すが、device_idでは絞る。"""
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


def test_malformed_eid_falls_back_to_s3(tmp_path, monkeypatch):
    """eidが device_id 書式でなければ raw側キーを組み立てられないので素直にGETする。"""
    monkeypatch.setattr(s3cache, "CACHE_ROOT", tmp_path)
    stub = _StubS3()
    client = s3cache.CachedS3(stub)
    key = _events_key(eid="not-a-device-id")

    body = client.get_object(Bucket="b", Key=key)["Body"].read()

    assert body == b"from-s3"
    assert stub.calls == [key]


def test_ambiguous_cross_prefix_hit_falls_back_to_s3(tmp_path, monkeypatch):
    """同じdevice・同じtsで複数イベントにコピーされている(原理上ほぼ起き得ない)場合は
    どれが正しいか決められないので安全側でS3へ通す。"""
    monkeypatch.setattr(s3cache, "CACHE_ROOT", tmp_path)
    for eid in (f"{DEVICE}-100", f"{DEVICE}-200"):
        p = tmp_path / _events_key(eid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"event-{eid}".encode())

    stub = _StubS3()
    client = s3cache.CachedS3(stub)
    body = client.get_object(Bucket="b", Key=_raw_key())["Body"].read()

    assert body == b"from-s3"
    assert stub.calls == [_raw_key()]
