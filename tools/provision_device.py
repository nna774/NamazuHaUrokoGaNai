"""デバイス払い出し。マニフェスト1枚からNVSプロビジョニング用ヘッダ/terraform/
焼くenv を導出する。

docs/design.md「多点運用時のデバイス払い出し」の実装。設計の要点は2つ。

- **変動軸を混ぜない**。個体差(device_id・HMAC鍵・WiFi)だけを生成対象にする。
  ボード差とセンサ差は platformio の `[env:]` が持つので、マニフェストは
  「どの env で焼くか」だけを覚える。config.h は生成しない。
- **HMAC鍵は両面**。ファーム(NVS)とサーバ(ingest Lambda の環境変数)の両方に
  同じ値が要る。片面だけ更新すると必ず認証が落ちるので、同じ1ファイルから両方を出す。

マニフェスト `tools/devices.json` は**鍵を含むので gitignore 対象**。
雛形は `tools/devices.example.json`。

デバイス識別情報・秘密・エンドポイントURLはコンパイル時定数(旧secrets.h)ではなく
NVSに持つ（docs/ota.md §2「バイナリの秘密情報を分離しないと成立しない」——pull型OTAで
envごとに1本のバイナリを公開URLへ置くと、コンパイル時に焼き込んだ秘密がそのまま
世界に漏れる）。`provision-h`が生成する`secrets_provision.h`は書き込み専用の
`[env:provision]`ビルドだけが読み、NVSへ書いて役目を終える。

    # 2台目を作る（鍵は自動生成）
    python tools/provision_device.py add --id 2 --label 湯沢-ADXL355 --sensor adxl355

    # NVS書き込み用ヘッダを生成し、provisionビルドで焼く（1回だけ）
    python tools/provision_device.py provision-h --id 2
    cd firmware && pio run -e adxl355-provision -t upload --upload-port <USBポート>

    # 続けて通常のfirmwareを焼く（NVSはOTAでも保持されるので以降は不要）
    pio run -e "$(python ../tools/provision_device.py env --id 2)" -t upload \\
        --upload-port <USBポート>

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
SECRETS_PROVISION_H = ROOT / "firmware" / "src" / "secrets_provision.h"

# センサ種別 -> 既定の platformio env。ボードも変えるなら env を直接指定する。
SENSOR_ENV = {
    "iis3dhhc": "esp32dev",
    "adxl355": "adxl355",
    # ESP32-C3スーパーミニ(docs/piezo.md)。provision専用envは[env:piezo-provision]
    # （加速度センサ2種のように<env>-provisionを機械的に付けても導出できるが、
    # NVS書き込み先ボード種別を明示するため既定envの表にはそのまま載せておく）。
    "piezo": "piezo",
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


def render_provision_h(m: dict, d: dict) -> str:
    """firmware/src/secrets_provision.h の中身。secrets_provision.h.example と項目を揃えること。

    書き込み専用の[env:provision]/[env:adxl355-provision]ビルドだけが読み、
    NVSへ書いて役目を終える（通常のfirmwareはNVSから読む。docs/ota.md §2）。
    """
    ingest = d.get("ingest_url") or m["ingest_url"]
    alert = d.get("alert_url") or m["alert_url"]
    api = d.get("api_url") or m["api_url"]
    ota_base = d.get("ota_base_url") or m["ota_base_url"]
    label = d.get("label", "")
    return f"""#pragma once
// provision_device.py が tools/devices.json から生成した。直接編集するな。
// device {d['id']}{f" ({label})" if label else ""} / env={d['env']}
// [env:provision]/[env:adxl355-provision] だけがこれを読みNVSへ書く。焼いたら
// このファイルは用済み（通常のfirmwareはNVSから読む。docs/ota.md §2）。

#include <cstdint>

static constexpr uint32_t kProvDeviceId = {d['id']};

static constexpr const char* kProvWifiSsid = "{d['wifi_ssid']}";
static constexpr const char* kProvWifiPass = "{d['wifi_pass']}";

static constexpr const char* kProvHmacSecret = "{d['hmac_secret']}";

static constexpr const char* kProvIngestUrl = "{ingest}";
static constexpr const char* kProvAlertUrl = "{alert}";
static constexpr const char* kProvApiUrl = "{api}";
static constexpr const char* kProvOtaBaseUrl = "{ota_base}";
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


def cmd_provision_h(args) -> int:
    m = load()
    d = find(m, args.id)
    text = render_provision_h(m, d)
    if args.stdout:
        print(text, end="")
        return 0
    out = Path(args.out) if args.out else SECRETS_PROVISION_H
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

    s = sub.add_parser("provision-h",
                       help="firmware/src/secrets_provision.h を生成（[env:provision]用）")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--out", help="出力先（既定 firmware/src/secrets_provision.h）")
    s.add_argument("--stdout", action="store_true", help="書かずに標準出力へ")
    s.add_argument("--force", action="store_true", help="既存を上書きする")
    s.set_defaults(func=cmd_provision_h)

    sub.add_parser("tfvars", help="terraform.tfvars 用の device_hmac_secrets を出す") \
        .set_defaults(func=cmd_tfvars)

    e = sub.add_parser("env", help="焼くべき platformio env 名を出す")
    e.add_argument("--id", type=int, required=True)
    e.set_defaults(func=cmd_env)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
