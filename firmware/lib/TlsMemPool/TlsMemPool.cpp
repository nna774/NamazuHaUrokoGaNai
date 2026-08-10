#include "TlsMemPool.h"

#include <Arduino.h>
#include <mbedtls/platform.h>

#include <cstdint>
#include <cstring>

namespace tlsmempool {
namespace {

// 実機計測(docs/log/2026-08-10-tls-dedicated-pool.md、firmware/lib/
// TlsAllocProbe)でのピーク同時確保量は48304バイト(largest_single=16717B)。
// 約35%の余裕を見て64KiBにする。将来OTA(docs/ota.md、未着手)がこのプールを
// 通るようになったら、そちら固有のTLS footprintも実機で測って見直すこと
// （OTA先はS3/CloudFront、ingest/alertとは別ホストでcert chainが異なりうる）。
constexpr size_t kPoolBytes = 64 * 1024;
constexpr size_t kAlignment = 8;
constexpr uint32_t kMagicFree = 0x66726565;  // "free"
constexpr uint32_t kMagicUsed = 0x75736564;  // "used"

// プール内の各ブロック(使用中・空き問わず)の先頭に置くヘッダ。物理的な
// 前後リンクだけを持つ境界タグ方式——空きブロック専用のリストは持たず、
// 確保のたびに物理リストを先頭から走査する(first-fit)。プールは64KiBかつ
// 1回のTLSハンドシェイクで数千回程度の出入りなので、線形走査でも実用上
// 問題にならない(ESP32 240MHzに対しネットワーク待ちの方が桁違いに遅い)。
struct BlockHeader {
  uint32_t magic;
  uint32_t size;          // このヘッダに続く利用可能バイト数
  BlockHeader* physNext;  // プール内で物理的に次のブロック(末尾ならnullptr)
  BlockHeader* physPrev;  // 物理的に前のブロック(先頭ならnullptr)
};

uint8_t* sPoolBase = nullptr;
BlockHeader* sFirstBlock = nullptr;

size_t sCallCount = 0;
size_t sFreeCount = 0;
size_t sFailCount = 0;
size_t sPeakOutstanding = 0;
long sCurrentOutstanding = 0;

size_t alignUp(size_t n) { return (n + (kAlignment - 1)) & ~(kAlignment - 1); }

void* dataOf(BlockHeader* b) { return reinterpret_cast<uint8_t*>(b) + sizeof(BlockHeader); }

BlockHeader* headerOf(void* data) {
  return reinterpret_cast<BlockHeader*>(reinterpret_cast<uint8_t*>(data) - sizeof(BlockHeader));
}

// 空いている最初の十分なブロックを探す(first-fit)。余りが
// ヘッダ+アラインメント以上残るなら分割し、残りを新しい空きブロックにする。
void* poolAlloc(size_t bytes) {
  size_t need = alignUp(bytes);
  for (BlockHeader* b = sFirstBlock; b != nullptr; b = b->physNext) {
    if (b->magic != kMagicFree || b->size < need) continue;

    size_t remain = b->size - need;
    if (remain > sizeof(BlockHeader) + kAlignment) {
      auto* newFree =
          reinterpret_cast<BlockHeader*>(reinterpret_cast<uint8_t*>(dataOf(b)) + need);
      newFree->magic = kMagicFree;
      newFree->size = remain - sizeof(BlockHeader);
      newFree->physNext = b->physNext;
      newFree->physPrev = b;
      if (newFree->physNext) newFree->physNext->physPrev = newFree;
      b->physNext = newFree;
      b->size = need;
    }
    b->magic = kMagicUsed;
    return dataOf(b);
  }
  return nullptr;
}

// bへ物理的に次のブロックが空きなら吸収する(断片化を溜めないための即時結合)。
void mergeWithNext(BlockHeader* b) {
  BlockHeader* n = b->physNext;
  if (!n || n->magic != kMagicFree) return;
  b->size += sizeof(BlockHeader) + n->size;
  b->physNext = n->physNext;
  if (b->physNext) b->physNext->physPrev = b;
}

void* poolCalloc(size_t nmemb, size_t size) {
  size_t bytes = nmemb * size;
  sCallCount++;
  void* p = poolAlloc(bytes);
  if (!p) {
    sFailCount++;
    Serial.printf(
        "[tls-pool] calloc FAILED for %u bytes (pool exhausted, call #%u, "
        "outstanding=%ld peak=%u)\n",
        (unsigned)bytes, (unsigned)sCallCount, sCurrentOutstanding, (unsigned)sPeakOutstanding);
    return nullptr;
  }
  memset(p, 0, bytes);
  sCurrentOutstanding += static_cast<long>(bytes);
  if (sCurrentOutstanding > static_cast<long>(sPeakOutstanding)) {
    sPeakOutstanding = static_cast<size_t>(sCurrentOutstanding);
  }
  return p;
}

void poolFree(void* ptr) {
  if (!ptr) return;
  BlockHeader* b = headerOf(ptr);
  if (b->magic != kMagicUsed) {
    // 二重free/プール外ポインタ/破損のいずれか。プール全体を巻き込む
    // クラッシュより、ここで無視して痕跡だけ残す方が安全。
    Serial.printf("[tls-pool] free() on non-used block (magic=%08x) — ignoring\n",
                  (unsigned)b->magic);
    return;
  }
  size_t bytes = b->size;
  b->magic = kMagicFree;
  mergeWithNext(b);
  if (b->physPrev && b->physPrev->magic == kMagicFree) {
    mergeWithNext(b->physPrev);
  }
  sFreeCount++;
  sCurrentOutstanding -= static_cast<long>(bytes);
}

}  // namespace

void install() {
  sPoolBase = static_cast<uint8_t*>(malloc(kPoolBytes));
  if (!sPoolBase) {
    Serial.printf(
        "[tls-pool] FATAL: failed to reserve %u byte pool, mbedTLS keeps using the "
        "general heap (degraded, no isolation)\n",
        (unsigned)kPoolBytes);
    return;
  }
  sFirstBlock = reinterpret_cast<BlockHeader*>(sPoolBase);
  sFirstBlock->magic = kMagicFree;
  sFirstBlock->size = kPoolBytes - sizeof(BlockHeader);
  sFirstBlock->physNext = nullptr;
  sFirstBlock->physPrev = nullptr;

  mbedtls_platform_set_calloc_free(poolCalloc, poolFree);
  Serial.printf("[tls-pool] installed: %u byte dedicated pool for mbedTLS\n",
                (unsigned)kPoolBytes);
}

}  // namespace tlsmempool
