import json
import re

import pytest

import provision_device as pd


def manifest(**over):
    m = {
        "ingest_url": "https://ingest.example/",
        "alert_url": "https://ingest.example/alert",
        "api_url": "https://api.example",
        "ota_base_url": "https://ota.example",
        "devices": [
            {"id": 1, "label": "湯沢-IIS3DHHC", "sensor": "iis3dhhc", "env": "esp32dev",
             "wifi_ssid": "ssid1", "wifi_pass": "pass1", "hmac_secret": "aa" * 32},
            {"id": 2, "label": "湯沢-ADXL355", "sensor": "adxl355", "env": "adxl355",
             "wifi_ssid": "ssid2", "wifi_pass": "pass2", "hmac_secret": "bb" * 32},
        ],
    }
    m.update(over)
    return m


def test_new_secret_is_64_hex_chars():
    s = pd.new_secret()
    assert re.fullmatch(r"[0-9a-f]{64}", s)
    assert pd.new_secret() != s


def test_validate_rejects_duplicate_id():
    m = manifest()
    m["devices"].append(dict(m["devices"][0]))
    with pytest.raises(ValueError, match="重複"):
        pd.validate(m)


def test_validate_rejects_missing_secret():
    m = manifest()
    m["devices"][1]["hmac_secret"] = ""
    with pytest.raises(ValueError, match="足りない"):
        pd.validate(m)


def test_provision_h_has_every_field_the_firmware_needs():
    """secrets_provision.h.example と同じ定数が全部出ること。欠けると書き込みが落ちる。"""
    text = pd.render_provision_h(manifest(), manifest()["devices"][1])
    for name in ("kProvWifiSsid", "kProvWifiPass", "kProvIngestUrl", "kProvAlertUrl",
                 "kProvApiUrl", "kProvOtaBaseUrl", "kProvDeviceId", "kProvHmacSecret"):
        assert name in text, name
    assert "kProvDeviceId = 2;" in text
    assert "bb" * 32 in text
    assert "ssid2" in text


def test_provision_h_url_override_per_device():
    m = manifest()
    m["devices"][0]["ingest_url"] = "https://other.example/"
    text = pd.render_provision_h(m, m["devices"][0])
    assert "https://other.example/" in text
    assert "https://ingest.example/alert" in text  # 上書きしていない方は共通値


def test_tfvars_keys_are_strings_matching_device_ids():
    """terraform の map キーは文字列。X-Namz-Device の表記と一致させる必要がある。"""
    out = pd.render_tfvars(manifest())
    assert out.startswith("device_hmac_secrets = {")
    assert f'"1" = "{"aa" * 32}"' in out
    assert f'"2" = "{"bb" * 32}"' in out


def test_provision_h_and_tfvars_carry_the_same_key():
    """両面に同じ鍵が出ること。ここがずれると必ず認証が落ちる（設計の主眼）。"""
    m = manifest()
    d = pd.find(m, 2)
    assert d["hmac_secret"] in pd.render_provision_h(m, d)
    assert d["hmac_secret"] in pd.render_tfvars(m)


def test_load_validates(tmp_path):
    p = tmp_path / "devices.json"
    bad = manifest()
    bad["devices"][0]["env"] = ""
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        pd.load(p)


def test_example_manifest_is_valid():
    """雛形がそのまま validate を通ること（コピーして値を埋めるだけで使える）。"""
    with open(pd.ROOT / "tools" / "devices.example.json") as f:
        pd.validate(json.load(f))


def test_sensor_env_matches_platformio():
    """SENSOR_ENV の env が platformio.ini に実在すること。"""
    ini = (pd.ROOT / "firmware" / "platformio.ini").read_text()
    for sensor, env in pd.SENSOR_ENV.items():
        assert f"[env:{env}]" in ini, f"{sensor} -> {env} が platformio.ini に無い"
