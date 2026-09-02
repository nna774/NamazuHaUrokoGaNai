# arduino-esp32 2.x系(esp32dev/adxl355等、release/v2.xブランチ)の
# WiFiGenericClass::hostByName()をビルド時パッチする。3.x系(pioarduino)には
# この形のWiFiGeneric.cppが無い(NetworkManager.cppを使う、
# patch_network_manager.py側で別途対処済み)ため、対象ファイルが無い場合は
# 何もしない——このスクリプトを3.x系のenvに混ぜても安全。
#
# バグ: hostByName()が呼ぶdns_gethostbyname()はTCPIPスレッド上での実行を
# 要求するが、この関数自体はTCPIPスレッド以外(WiFi.hostByName()の呼び出し元)
# から直接呼ばれる。TCPIPスレッド外からlwIP内部のDNS関数を呼ぶと、保留中の
# 他のDNS問い合わせのコールバックへ再入する等でlwIP内部状態を壊し、実機で
# udp_sendto/tcp_listen_input等でのNULL参照クラッシュを繰り返し発生させて
# いた(NamazuHaUrokoGaNai PR#191/PR#193)。
#
# 修正: espressif/arduino-esp32#8672(2023-12-05マージ、3.x系列にのみ反映済み・
# release/v2.xへは未バックポート)と同じ手法で、dns_gethostbyname()を
# esp_netif_tcpip_exec()経由でTCPIPスレッド上に委譲する。
# docs/log/2026-09-01-pioarduino-arduino3-poc.md参照。

Import("env")

import os

SENTINEL = "NamazuHaUrokoGaNaiローカルパッチ: hostByName TCPIPスレッド委譲"

OLD_INCLUDE = "#include <esp_event.h>\n#include \"lwip/ip_addr.h\""
NEW_INCLUDE = "#include <esp_event.h>\n#include <esp_netif.h>\n#include \"lwip/ip_addr.h\""

HELPER = '''static void wifi_dns_found_callback(const char *name, const ip_addr_t *ipaddr, void *callback_arg)
{
    if(ipaddr) {
        (*reinterpret_cast<IPAddress*>(callback_arg)) = ipaddr->u_addr.ip4.addr;
    }
    xEventGroupSetBits(_arduino_event_group, WIFI_DNS_DONE_BIT);
}

// ''' + SENTINEL + '''
// dns_gethostbyname()はlwIPのTCPIPスレッド上での実行を要求するが、
// hostByName()自体はそれ以外のタスクから直接呼ばれる。espressif/arduino-esp32
// #8672(3.x系列にのみ反映済み)と同じ手法でesp_netif_tcpip_exec()経由に
// 委譲する(docs/log/2026-09-01-pioarduino-arduino3-poc.md)。
typedef struct namzGethostbynameParams {
    const char *hostname;
    ip_addr_t addr;
    void *callback_arg;
} namzGethostbynameParams_t;

static esp_err_t namz_wifi_gethostbyname_tcpip_ctx(void *param)
{
    namzGethostbynameParams_t *p = static_cast<namzGethostbynameParams_t *>(param);
    return dns_gethostbyname(p->hostname, &p->addr, &wifi_dns_found_callback, p->callback_arg);
}'''

OLD_HOSTBYNAME_BODY = (
    "    if (!aResult.fromString(aHostname))\n"
    "    {\n"
    "        ip_addr_t addr;\n"
    "        aResult = static_cast<uint32_t>(0);\n"
    "        waitStatusBits(WIFI_DNS_IDLE_BIT, 16000);\n"
    "        clearStatusBits(WIFI_DNS_IDLE_BIT | WIFI_DNS_DONE_BIT);\n"
    "        err_t err = dns_gethostbyname(aHostname, &addr, &wifi_dns_found_callback, &aResult);\n"
    "        if(err == ERR_OK && addr.u_addr.ip4.addr) {\n"
    "            aResult = addr.u_addr.ip4.addr;\n"
    "        } else if(err == ERR_INPROGRESS) {"
)
NEW_HOSTBYNAME_BODY = (
    "    if (!aResult.fromString(aHostname))\n"
    "    {\n"
    "        namzGethostbynameParams_t params;\n"
    "        params.hostname = aHostname;\n"
    "        params.callback_arg = &aResult;\n"
    "        aResult = static_cast<uint32_t>(0);\n"
    "        waitStatusBits(WIFI_DNS_IDLE_BIT, 16000);\n"
    "        clearStatusBits(WIFI_DNS_IDLE_BIT | WIFI_DNS_DONE_BIT);\n"
    "        err_t err = esp_netif_tcpip_exec(namz_wifi_gethostbyname_tcpip_ctx, &params);\n"
    "        if(err == ERR_OK && params.addr.u_addr.ip4.addr) {\n"
    "            aResult = params.addr.u_addr.ip4.addr;\n"
    "        } else if(err == ERR_INPROGRESS) {"
)


def patch_wifi_generic():
    framework_dir = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    if not framework_dir:
        return
    path = os.path.join(framework_dir, "libraries", "WiFi", "src", "WiFiGeneric.cpp")
    if not os.path.exists(path):
        # 3.x系にはこのファイルが無い(NetworkManager.cppを使う)。何もしない。
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if SENTINEL in content:
        print("[namz-patch] WiFiGeneric.cpp: already patched, skip")
        return

    original = content
    content = content.replace(OLD_INCLUDE, NEW_INCLUDE, 1)
    content = content.replace(
        "static void wifi_dns_found_callback(const char *name, const ip_addr_t *ipaddr, void *callback_arg)\n"
        "{\n"
        "    if(ipaddr) {\n"
        "        (*reinterpret_cast<IPAddress*>(callback_arg)) = ipaddr->u_addr.ip4.addr;\n"
        "    }\n"
        "    xEventGroupSetBits(_arduino_event_group, WIFI_DNS_DONE_BIT);\n"
        "}",
        HELPER,
        1,
    )
    content = content.replace(OLD_HOSTBYNAME_BODY, NEW_HOSTBYNAME_BODY, 1)

    if content == original:
        print(
            "[namz-patch] WARNING: WiFiGeneric.cpp did not match expected "
            "content, patch NOT applied (framework version may have changed)"
        )
        return
    if SENTINEL not in content:
        print(
            "[namz-patch] WARNING: some replacements in WiFiGeneric.cpp did "
            "not match, patch partially applied or failed"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[namz-patch] WiFiGeneric.cpp: patched (hostByName tcpip_exec)")


patch_wifi_generic()
