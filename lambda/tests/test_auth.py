import hashlib
import hmac

import pytest

from common import auth


def test_verify_ok(monkeypatch):
    monkeypatch.setenv("NAMZ_HMAC_SECRET", "secret")
    body = b"hello"
    sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    auth.verify("1", body, sig)  # 例外が出なければOK


def test_verify_rejects_bad_sig(monkeypatch):
    monkeypatch.setenv("NAMZ_HMAC_SECRET", "secret")
    with pytest.raises(auth.AuthError):
        auth.verify("1", b"hello", "deadbeef")


def test_per_device_secret(monkeypatch):
    monkeypatch.setenv("NAMZ_HMAC_SECRET_7", "seven")
    monkeypatch.setenv("NAMZ_HMAC_SECRET", "default")
    body = b"x"
    sig = hmac.new(b"seven", body, hashlib.sha256).hexdigest()
    auth.verify("7", body, sig)
