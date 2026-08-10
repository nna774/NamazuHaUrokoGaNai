#include "TlsAllocProbe.h"

#include <Arduino.h>
#include <mbedtls/platform.h>

#include <cstdint>
#include <cstring>

namespace tlsallocprobe {
namespace {

// 確保のたびに直前へ埋め込むヘッダ。free時にサイズを読み戻すためだけの
// もので、アライメント調整は行わない（mbedTLS内部の確保サイズはこのSDKの
// 実装上すべて8の倍数以上になっており、size_t 1個ぶんのオフセットで
// アライメント要件を壊した実例は今のところ無い）。
struct AllocHeader {
  size_t bytes;
};

size_t sCallCount = 0;
size_t sFreeCount = 0;
size_t sFailCount = 0;
size_t sTotalBytesRequested = 0;
long sCurrentOutstanding = 0;
size_t sPeakOutstanding = 0;
size_t sLargestSingleAlloc = 0;

void* probeCalloc(size_t nmemb, size_t size) {
  size_t bytes = nmemb * size;
  size_t total = bytes + sizeof(AllocHeader);
  auto* raw = static_cast<uint8_t*>(calloc(1, total));
  if (!raw) {
    sFailCount++;
    Serial.printf("[tls-alloc-probe] calloc FAILED for %u bytes (call #%u)\n", (unsigned)bytes,
                  (unsigned)(sCallCount + 1));
    return nullptr;
  }
  auto* hdr = reinterpret_cast<AllocHeader*>(raw);
  hdr->bytes = bytes;

  sCallCount++;
  sTotalBytesRequested += bytes;
  sCurrentOutstanding += static_cast<long>(bytes);
  if (sCurrentOutstanding > static_cast<long>(sPeakOutstanding)) {
    sPeakOutstanding = static_cast<size_t>(sCurrentOutstanding);
  }
  if (bytes > sLargestSingleAlloc) {
    sLargestSingleAlloc = bytes;
  }
  return raw + sizeof(AllocHeader);
}

void probeFree(void* ptr) {
  if (!ptr) return;
  auto* raw = reinterpret_cast<uint8_t*>(ptr) - sizeof(AllocHeader);
  auto* hdr = reinterpret_cast<AllocHeader*>(raw);
  sCurrentOutstanding -= static_cast<long>(hdr->bytes);
  sFreeCount++;
  free(raw);
}

}  // namespace

void install() {
  mbedtls_platform_set_calloc_free(probeCalloc, probeFree);
  Serial.println("[tls-alloc-probe] mbedtls calloc/free hook installed");
}

void printIfChanged() {
  static size_t sLastCallCount = 0;
  static size_t sLastFreeCount = 0;
  if (sCallCount == sLastCallCount && sFreeCount == sLastFreeCount) return;
  sLastCallCount = sCallCount;
  sLastFreeCount = sFreeCount;
  Serial.printf(
      "[tls-alloc-probe] calls=%u frees=%u fails=%u outstanding=%ld peak=%u "
      "largest_single=%u total_requested=%u\n",
      (unsigned)sCallCount, (unsigned)sFreeCount, (unsigned)sFailCount, sCurrentOutstanding,
      (unsigned)sPeakOutstanding, (unsigned)sLargestSingleAlloc,
      (unsigned)sTotalBytesRequested);
}

}  // namespace tlsallocprobe
