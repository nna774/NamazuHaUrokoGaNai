# arduino-esp32 3.x系(pioarduino)のNetworkClientSecure::connect(host,...)を
# ビルド時パッチする。2.x系(esp32dev/adxl355等)にはNetworkClientSecure.cppの
# この形の実装が無い(WiFiClientSecure.cppを使う)ため、対象コードが無い場合は
# 何もしない——このスクリプトを[env:pioarduino-fake-sensor]以外のenvに
# 混ぜても安全。
#
# バグ: NetworkManager::hostByName()は成功時に1を返すが、失敗時は
# lwip_getaddrinfo()由来のEAI_*系コード(内部でerr_t(符号付き8bit)へ切り詰め
# られ負値になる)を返す——0を返すことは無い。ところがNetworkClientSecure.cpp
# の呼び出し側は`if (!Network.hostByName(host, address))`という「戻り値が
# ちょうど0の時だけ失敗」という判定になっており、非0の失敗コードを常に
# 「成功」と誤判定する。結果、hostByName()が失敗してaddressが0.0.0.0のまま
# でもガードで弾かれずstart_ssl_client()まで進み、0.0.0.0宛にTCP接続を試みる
# （実機のスイッチログで"martian destination 0.0.0.0"を確認済み）。
# docs/log/2026-09-01-pioarduino-arduino3-poc.md参照。

Import("env")

import os

SENTINEL = "NamazuHaUrokoGaNaiローカルパッチ: hostByName失敗判定"

OLD_CHECK = "  if (!Network.hostByName(host, address)) {\n    return 0;\n  }"
NEW_CHECK = (
    "  // " + SENTINEL + "\n"
    "  // hostByName()は成功時のみ1を返す。失敗時は0ではなく非0のエラーコード\n"
    "  // (EAI_*系がerr_tへ切り詰められた負値)を返すため、!演算子での判定は\n"
    "  // 常に成功扱いしてしまう。\n"
    "  if (Network.hostByName(host, address) != 1) {\n"
    "    return 0;\n"
    "  }"
)


def patch_network_client_secure():
    framework_dir = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    if not framework_dir:
        return
    path = os.path.join(
        framework_dir, "libraries", "NetworkClientSecure", "src", "NetworkClientSecure.cpp"
    )
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if SENTINEL in content:
        print("[namz-patch] NetworkClientSecure.cpp: already patched, skip")
        return

    original = content
    count = content.count(OLD_CHECK)
    content = content.replace(OLD_CHECK, NEW_CHECK)

    if content == original or count == 0:
        print(
            "[namz-patch] WARNING: NetworkClientSecure.cpp did not match expected "
            "content, patch NOT applied (framework version may have changed)"
        )
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[namz-patch] NetworkClientSecure.cpp: patched {count} call site(s)")


patch_network_client_secure()
