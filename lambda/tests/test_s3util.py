from common import s3util


def test_coredump_key_format():
    key = s3util.coredump_key(2, "326488d", 1_756_400_000_000_000)
    assert key == "coredump/0002/326488d-00001756400000000000.bin"


def test_coredump_key_zero_pads_device_id():
    key = s3util.coredump_key(7, "abc123", 0)
    assert key.startswith("coredump/0007/")
