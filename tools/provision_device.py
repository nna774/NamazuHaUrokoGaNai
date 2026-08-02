"""デバイス払い出し。マニフェスト1枚から secrets.h / terraform / 焼くenv を導出する。

docs/design.md「多点運用時のデバイス払い出し」の実装。設計の要点は2つ。

- **変動軸を混ぜない**。個体差(device_id・HMAC鍵・WiFi)だけを生成対象にする。
  ボード差とセンサ差は platformio の `[env:]` が持つので、マニフェストは
  「どの env で焼くか」だけを覚える。config.h は生成しない。
- **HMAC鍵は両面**。ファーム(secrets.h)とサーバ(ingest Lambda の環境変数)の両方に
  同じ値が要る。片面だけ更新すると必ず認証が落ちるので、同じ1ファイルから両方を出す。

マニフェスト `tools/devices.json` は**鍵を含むので gitignore 対象**。
雛形は `tools/devices.example.json`。

    # 2台目を作る（鍵は自動生成）
    python tools/provision_device.py add --id 2 --label 湯沢-ADXL355 --sensor adxl355

    # 焼く前に secrets.h を差し替える
    python tools/provision_device.py secrets-h --id 2
    cd firmware && pio run -e "$(python ../tools/provision_device.py env --id 2)" -t upload

    # サーバ側へ登録（出力を terraform/terraform.tfvars に貼って apply）
    python tools/provision_device.py tfvars
"""

from __future__ import annotations

import argparse
import json
import os
import secrets as pysecrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tools" / "devices.json"
SECRETS_H = ROOT / "firmware" / "src" / "secrets.h"

# センサ種別 -> 既定の platformio env。ボードも変えるなら env を直接指定する。
SENSOR_ENV = {
    "iis3dhhc": "esp32dev",
    "adxl355": "adxl355",
}

REQUIRED_FIELDS = ("id", "env", "wifi_ssid", "wifi_pass", "hmac_secret")


def new_secret() -> str:
    """HMAC共有鍵。ingest は文字列をそのまま鍵に使う（auth.verify）。"""
    return pysecrets.token_hex(32)


def load(path: Path = MANIFEST) -> dict:
    if not path.exists():
        raise SystemExit(
            f"{path} が無い。tools/devices.example.json をコピーして作れ（gitignore対象）")
    with open(path) as f:
        m = json.load(f)
    validate(m)
    return m


def validate(m: dict) -> None:
    devices = m.get("devices")
    if not isinstance(devices, list):
        raise ValueError("devices が配列でない")
    seen = set()
    for d in devices:
        missing = [k for k in REQUIRED_FIELDS if not d.get(k)]
        if missing:
            raise ValueError(f"device {d.get('id')}: 項目が足りない {missing}")
        if d["id"] in seen:
            raise ValueError(f"device_id {d['id']} が重複している")
        seen.add(d["id"])


def find(m: dict, device_id: int) -> dict:
    for d in m["devices"]:
        if d["id"] == device_id:
            return d
    raise SystemExit(f"device {device_id} がマニフェストに無い")


def render_secrets_h(m: dict, d: dict) -> str:
    """firmware/src/secrets.h の中身。secrets.h.example と項目を揃えること。"""
    ingest = d.get("ingest_url") or m["ingest_url"]
    alert = d.get("alert_url") or m["alert_url"]
    label = d.get("label", "")
    return f"""#pragma once
// provision_device.py が tools/devices.json から生成した。直接編集するな。
// device {d['id']}{f" ({label})" if label else ""} / env={d['env']}

#include <cstdint>

static constexpr const char* kWifiSsid = "{d['wifi_ssid']}";
static constexpr const char* kWifiPass = "{d['wifi_pass']}";

static constexpr const char* kIngestUrl = "{ingest}";
static constexpr const char* kAlertUrl = "{alert}";

static constexpr uint32_t kDeviceId = {d['id']};

static constexpr const char* kHmacSecret = "{d['hmac_secret']}";
"""


def render_tfvars(m: dict) -> str:
    """terraform.tfvars に貼る device_hmac_secrets。ingest の環境変数になる。"""
    lines = ["device_hmac_secrets = {"]
    for d in sorted(m["devices"], key=lambda x: x["id"]):
        label = d.get("label", "")
        lines.append(f'  "{d["id"]}" = "{d["hmac_secret"]}"'
                     + (f"  # {label}" if label else ""))
    lines.append("}")
    return "\n".join(lines)


def cmd_list(args) -> int:
    m = load()
    for d in sorted(m["devices"], key=lambda x: x["id"]):
        print(f"{d['id']:>4}  env={d['env']:<20} sensor={d.get('sensor', '?'):<10} "
              f"{d.get('label', '')}")
    return 0


def cmd_add(args) -> int:
    path = MANIFEST
    m = load(path)
    if any(d["id"] == args.id for d in m["devices"]):
        raise SystemExit(f"device {args.id} は既にある")
    env = args.env or SENSOR_ENV.get(args.sensor)
    if not env:
        raise SystemExit(f"--env を指定しろ（--sensor {args.sensor} の既定が無い）")
    d = {
        "id": args.id,
        "label": args.label or "",
        "sensor": args.sensor,
        "env": env,
        "wifi_ssid": args.wifi_ssid or m.get("default_wifi_ssid", ""),
        "wifi_pass": args.wifi_pass or m.get("default_wifi_pass", ""),
        "hmac_secret": new_secret(),
    }
    m["devices"].append(d)
    validate(m)
    with open(path, "w") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"# device {args.id} を {path} に追加した（env={env}）")
    print("# 次: secrets-h で焼く鍵を出し、tfvars でサーバ側にも登録しろ。片面だけだと認証が落ちる。")
    return 0


def cmd_secrets_h(args) -> int:
    m = load()
    d = find(m, args.id)
    text = render_secrets_h(m, d)
    if args.stdout:
        print(text, end="")
        return 0
    out = Path(args.out) if args.out else SECRETS_H
    if out.exists() and not args.force:
        raise SystemExit(f"{out} が既にある。上書きするなら --force")
    out.write_text(text)
    print(f"# wrote {out} (device {d['id']}, env={d['env']})", file=sys.stderr)
    return 0


def cmd_tfvars(args) -> int:
    print(render_tfvars(load()))
    return 0


def cmd_env(args) -> int:
    print(find(load(), args.id)["env"])
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="マニフェストのデバイス一覧").set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="デバイスを1台足す（HMAC鍵を生成）")
    a.add_argument("--id", type=int, required=True)
    a.add_argument("--label", help="人間向けの名前（湯沢-ADXL355 など）")
    a.add_argument("--sensor", choices=sorted(SENSOR_ENV), default="adxl355")
    a.add_argument("--env", help="platformio の env 名。既定は --sensor から引く")
    a.add_argument("--wifi-ssid", dest="wifi_ssid")
    a.add_argument("--wifi-pass", dest="wifi_pass")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("secrets-h", help="firmware/src/secrets.h を生成")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--out", help="出力先（既定 firmware/src/secrets.h）")
    s.add_argument("--stdout", action="store_true", help="書かずに標準出力へ")
    s.add_argument("--force", action="store_true", help="既存を上書きする")
    s.set_defaults(func=cmd_secrets_h)

    sub.add_parser("tfvars", help="terraform.tfvars 用の device_hmac_secrets を出す") \
        .set_defaults(func=cmd_tfvars)

    e = sub.add_parser("env", help="焼くべき platformio env 名を出す")
    e.add_argument("--id", type=int, required=True)
    e.set_defaults(func=cmd_env)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
