#include "TlsMemPool.h"

#include <Arduino.h>
#include <mbedtls/platform.h>

#include "TlsMemPoolCore.h"

namespace tlsmempool {
namespace {

// 実機計測(docs/log/2026-08-10-tls-dedicated-pool.md、firmware/lib/
// TlsAllocProbe)でのピーク同時確保量は48304バイト(largest_single=16717B)。
// 実機検証(2026-08-10)で64KiBだと一般ヒープ(RAMキュー最大108KB+この確保分)を
// 同時に圧迫しすぎ、heap枯渇によるabortを誘発した(docs/log/2026-08-10-
// tls-dedicated-pool.md「実機検証」節)。mbedTLSはC実装でcalloc失敗を安全な
// エラー経路(TLS操作失敗→既存の指数バックオフ)として扱えるため、プール枯渇は
// abortより遥かに軽微——実測ピークへの余裕は35%から約8%(52KiB)まで削り、
// 一般ヒープ側に余裕を戻す。将来OTA(docs/ota.md、未着手)がこのプールを
// 通るようになったら、そちら固有のTLS footprintも実機で測って見直すこと
// （OTA先はS3/CloudFront、ingest/alertとは別ホストでcert chainが異なりうる）。
constexpr size_t kPoolBytes = 52 * 1024;

void warnToSerial(const char* msg) { Serial.println(msg); }

}  // namespace

void install() {
  auto* buf = static_cast<uint8_t*>(malloc(kPoolBytes));
  if (!buf) {
    Serial.printf(
        "[tls-pool] FATAL: failed to reserve %u byte pool, mbedTLS keeps using the "
        "general heap (degraded, no isolation)\n",
        (unsigned)kPoolBytes);
    return;
  }
  core::install(buf, kPoolBytes, warnToSerial);

  mbedtls_platform_set_calloc_free(core::poolCalloc, core::poolFree);
  Serial.printf("[tls-pool] installed: %u byte dedicated pool for mbedTLS\n",
                (unsigned)kPoolBytes);
}

}  // namespace tlsmempool
