"""_handle_coredump()の単体テスト（S3・通知はfakeで代替、DynamoDBには触れない経路）。"""

import os

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")
os.environ.setdefault("NAMZ_DEVICES_TABLE", "test-devices")
# ingest.handlerはモジュール読み込み時にboto3.resource("dynamodb")を呼ぶため、region未設定だと
# import自体がNoRegionErrorで失敗する（実行環境のLambdaでは常に設定されているため本番影響は無い）。
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")

import pytest

from ingest import handler as ingest  # noqa: E402


class FakeS3:
    def __init__(self):
        self.puts: list[dict] = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


class FakeNotifier:
    def __init__(self, *, fail=False):
        self.calls: list[tuple] = []
        self.fail = fail

    def notify(self, title, text, fields=None, **kwargs):
        if self.fail:
            raise RuntimeError("slack down")
        self.calls.append((title, text, fields))


@pytest.fixture
def fake_s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ingest, "s3", fake)
    return fake


def test_handle_coredump_stores_to_s3(fake_s3, monkeypatch):
    notifier = FakeNotifier()
    monkeypatch.setattr(ingest.notify, "from_env", lambda: notifier)

    resp = ingest._handle_coredump(b"\x7fELFdummy", "2", {"x-namz-fw-version": "326488d"})

    assert resp["statusCode"] == 200
    assert len(fake_s3.puts) == 1
    put = fake_s3.puts[0]
    assert put["Bucket"] == "test-bucket"
    assert put["Key"].startswith("coredump/0002/326488d-")
    assert put["Body"] == b"\x7fELFdummy"
    assert len(notifier.calls) == 1
    assert "326488d" in notifier.calls[0][1]


def test_handle_coredump_acks_even_if_notify_fails(fake_s3, monkeypatch):
    monkeypatch.setattr(ingest.notify, "from_env", lambda: FakeNotifier(fail=True))

    resp = ingest._handle_coredump(b"dummy", "1", {})

    # 通知が失敗してもS3保存が済んでいればACKする(_handle_batchの
    # devices.get_device失敗時と同じ「主経路ではないので握りつぶす」扱い)。
    assert resp["statusCode"] == 200
    assert len(fake_s3.puts) == 1


def test_handle_coredump_routes_from_handler(fake_s3, monkeypatch):
    monkeypatch.setattr(ingest.notify, "from_env", lambda: FakeNotifier())
    monkeypatch.setattr(ingest.auth, "verify", lambda device, raw, sig: None)

    event = {
        "rawPath": "/coredump",
        "headers": {
            "x-namz-device": "3",
            "x-namz-signature": "deadbeef",
            "x-namz-fw-version": "abc1234",
        },
        "body": "aGVsbG8=",  # "hello" (base64)
        "isBase64Encoded": True,
    }
    resp = ingest.handler(event, None)

    assert resp["statusCode"] == 200
    assert fake_s3.puts[0]["Body"] == b"hello"
    assert fake_s3.puts[0]["Key"].startswith("coredump/0003/abc1234-")
