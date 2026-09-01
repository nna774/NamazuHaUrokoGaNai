# arduino-esp32 3.x系(pioarduino)の NetworkManager::hostByName() をビルド時パッチする。
# 2.x系(esp32dev/adxl355等)にはNetworkManager.cppが存在しないため、対象ファイルが
# 無い場合は何もしない——このスクリプトを[env:pioarduino-fake-sensor]以外のenvに
# 混ぜても安全。
#
# パッチ内容:
# 1. dns_clear_cache()をesp_netif_tcpip_exec()経由でTCPIPスレッド上に委譲する。
#    TCPIPスレッド外から直接呼ぶと、保留中の他のDNS問い合わせ(SNTP等)の完了
#    コールバックへ再入し、そこがudp_new_ip_type等でassertする実機クラッシュを
#    確認済み（espressif/arduino-esp32#8672がWiFiGenericClass::hostByName()
#    [2.x系]に対して行ったのと同じ手法）。
# 2. DNS解決の成否・使用中のDNSサーバをSerial.printfで無条件に出す診断ログを追加。
#    hostByName()失敗時のconnection refusedが、実際にDNS解決自体が失敗している
#    のか、それとも別の原因かを切り分けるため。
#
# 3. lwip_getaddrinfo()は内部の本当のerr_t(netconn_gethostbyname_addrtype()の
#    戻り値)を全部EAI_FAIL(202)一つに握りつぶして返す実装になっており、しかも
#    そのEAI_FAIL(202)をNetworkManager::hostByName()側のerr_t(=符号付き8bit、
#    -128〜127)に代入すると 202-256=-54 に暗黙変換で切り詰められる——
#    「err=-54」はEXFULL(テーブル満杯)ではなく、単なるこの型不一致バグの産物
#    だったと判明。診断用にnetconn_gethostbyname_addrtype()を直接呼び本物の
#    err_t(=ERR_VAL(-6))を確認済み（この診断呼び出し自体はDNS問い合わせを
#    追加発生させ実機WDTを誘発したため、確認後にパッチから取り除いた）。
# 4. hostByName()失敗の瞬間、dns_table[]/dns_pcbs[]（nmで判明した固定アドレス、
#    ビルドのたびに要再確認）の生バイトをダンプする。coredumpにはタスクスタック
#    しか含まれずグローバル変数(BSS/DRAM)の検証ができないと判明したため
#    （ESP32既定のcoredump形式の制約。JTAGでのライブデバッグが理想だが手元に
#    無い）、実機で直接読む。
#
# 詳細: docs/log/2026-09-01-pioarduino-arduino3-poc.md

Import("env")

import os

SENTINEL = "NamazuHaUrokoGaNaiローカルパッチ"

DNS_CLEAR_CACHE_HELPER = '''NetworkManager::NetworkManager() {}

// NamazuHaUrokoGaNaiローカルパッチ: dns_clear_cache()はTCPIPスレッド外から呼ぶと
// 保留中の他のDNS問い合わせのコールバックへ再入し、そこがudp_new_ip_type等で
// assertする(docs/log/2026-09-01-pioarduino-arduino3-poc.md)。espressif/arduino-esp32
// #8672(WiFiGenericClass::hostByName、2.x系)と同じ手法でTCPIPスレッド上に委譲する。
static esp_err_t namz_dns_clear_cache_tcpip_ctx(void *) {
  dns_clear_cache();
  return ESP_OK;
}
'''

OLD_DNS_CLEAR_CACHE_CALL = "    dns_clear_cache();\n    log_d(\"Clearing DNS cache\");"
NEW_DNS_CLEAR_CACHE_CALL = (
    "    esp_netif_tcpip_exec(namz_dns_clear_cache_tcpip_ctx, nullptr);\n"
    "    log_d(\"Clearing DNS cache\");"
)

# 診断ログ: hasGlobalV4/V6判定後、実際に使われているDNSサーバを出す。
OLD_HINTS_BLOCK = (
    "  struct addrinfo hints;\n"
    "  memset(&hints, 0, sizeof(hints));\n"
    "  hints.ai_socktype = SOCK_STREAM;"
)
NEW_HINTS_BLOCK = (
    "  {\n"
    "    const ip_addr_t *namz_dns0 = dns_getserver(0);\n"
    "    const ip_addr_t *namz_dns1 = dns_getserver(1);\n"
    "    Serial.printf(\"[namz-dns] hostByName('%s') hasV4=%d hasV6=%d dns0=%s dns1=%s\\n\",\n"
    "                  aHostname, (int)hasGlobalV4Now, (int)hasGlobalV6Now,\n"
    "                  namz_dns0 ? ipaddr_ntoa(namz_dns0) : \"none\",\n"
    "                  namz_dns1 ? ipaddr_ntoa(namz_dns1) : \"none\");\n"
    "  }\n"
    "  struct addrinfo hints;\n"
    "  memset(&hints, 0, sizeof(hints));\n"
    "  hints.ai_socktype = SOCK_STREAM;"
)

# 診断ログ: IPv4(AF_UNSPEC)解決の成功/失敗をそのまま出す。
OLD_IPV4_SUCCESS_TAIL = (
    "    lwip_freeaddrinfo(res);\n"
    "    return 1;\n"
    "  }\n"
    "\n"
    "  log_e(\"DNS Failed for '%s' with error '%d'\", aHostname, err);\n"
    "  return err;\n"
    "}"
)
NEW_IPV4_SUCCESS_TAIL = (
    "    Serial.printf(\"[namz-dns] hostByName('%s') SUCCESS -> %s\\n\", aHostname,\n"
    "                  aResult.toString().c_str());\n"
    "    lwip_freeaddrinfo(res);\n"
    "    return 1;\n"
    "  }\n"
    "\n"
    "  Serial.printf(\"[namz-dns] hostByName('%s') FAILED err=%d\\n\", aHostname, err);\n"
    "  {\n"
    "    // 診断: dns_table[]/dns_pcbs[]の生バイトをダンプする(nm経由で判明した\n"
    "    // 固定アドレス。coredumpにはタスクスタックしか含まれずグローバル変数の\n"
    "    // 検証ができないと判明したため、失敗の瞬間に直接読む。\n"
    "    // docs/log/2026-09-01-pioarduino-arduino3-poc.md参照。アドレスは\n"
    "    // ビルドのたびにnmで再確認すること(リンク順で変わりうる)。\n"
    "    const uint8_t *namz_dns_table = (const uint8_t *)0x3ffc9310;\n"
    "    Serial.printf(\"[namz-dns] dns_table raw @0x3ffc9310:\\n\");\n"
    "    for (int i = 0; i < 512; i += 16) {\n"
    "      Serial.printf(\"  +%03d:\", i);\n"
    "      for (int j = 0; j < 16; j++) {\n"
    "        Serial.printf(\" %02x\", namz_dns_table[i + j]);\n"
    "      }\n"
    "      Serial.printf(\"  |\");\n"
    "      for (int j = 0; j < 16; j++) {\n"
    "        uint8_t c = namz_dns_table[i + j];\n"
    "        Serial.printf(\"%c\", (c >= 0x20 && c < 0x7f) ? c : '.');\n"
    "      }\n"
    "      Serial.printf(\"|\\n\");\n"
    "    }\n"
    "    const uint8_t *namz_dns_pcbs = (const uint8_t *)0x3ffc97b4;\n"
    "    Serial.printf(\"[namz-dns] dns_pcbs raw @0x3ffc97b4:\\n\");\n"
    "    for (int i = 0; i < 32; i += 16) {\n"
    "      Serial.printf(\"  +%03d:\", i);\n"
    "      for (int j = 0; j < 16; j++) {\n"
    "        Serial.printf(\" %02x\", namz_dns_pcbs[i + j]);\n"
    "      }\n"
    "      Serial.printf(\"\\n\");\n"
    "    }\n"
    "  }\n"
    "  log_e(\"DNS Failed for '%s' with error '%d'\", aHostname, err);\n"
    "  return err;\n"
    "}"
)

def patch_network_manager():
    framework_dir = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
    if not framework_dir:
        return
    path = os.path.join(
        framework_dir, "libraries", "Network", "src", "NetworkManager.cpp"
    )
    if not os.path.exists(path):
        # 2.x系にはこのファイルが無い(esp32dev/adxl355等)。何もしない。
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if SENTINEL in content:
        print("[namz-patch] NetworkManager.cpp: already patched, skip")
        return

    original = content
    content = content.replace(
        '#include "lwip/dns.h"', '#include "lwip/dns.h"\n#include "lwip/api.h"', 1
    )
    content = content.replace("NetworkManager::NetworkManager() {}", DNS_CLEAR_CACHE_HELPER, 1)
    content = content.replace(OLD_DNS_CLEAR_CACHE_CALL, NEW_DNS_CLEAR_CACHE_CALL, 1)
    content = content.replace(OLD_HINTS_BLOCK, NEW_HINTS_BLOCK, 1)
    content = content.replace(OLD_IPV4_SUCCESS_TAIL, NEW_IPV4_SUCCESS_TAIL, 1)

    if content == original:
        print(
            "[namz-patch] WARNING: NetworkManager.cpp did not match expected "
            "content, patch NOT applied (framework version may have changed)"
        )
        return
    if SENTINEL not in content:
        print(
            "[namz-patch] WARNING: some replacements in NetworkManager.cpp did "
            "not match, patch partially applied or failed"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[namz-patch] NetworkManager.cpp: patched (dns_clear_cache tcpip_exec + diagnostics)")


patch_network_manager()
