#include "TlsMemPoolCore.h"

#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace tlsmempool {
namespace core {
namespace {

constexpr size_t kAlignment = 8;
constexpr uint32_t kMagicFree = 0x66726565;  // "free"
constexpr uint32_t kMagicUsed = 0x75736564;  // "used"

// プール内の各ブロック(使用中・空き問わず)の先頭に置くヘッダ。物理的な
// 前後リンクだけを持つ境界タグ方式——空きブロック専用のリストは持たず、
// 確保のたびに物理リストを先頭から走査する(first-fit)。
struct BlockHeader {
  uint32_t magic;
  uint32_t size;          // このヘッダに続く利用可能バイト数
  BlockHeader* physNext;  // プール内で物理的に次のブロック(末尾ならnullptr)
  BlockHeader* physPrev;  // 物理的に前のブロック(先頭ならnullptr)
};

uint8_t* sPoolBase = nullptr;
size_t sPoolBytes = 0;
BlockHeader* sFirstBlock = nullptr;
WarnFn sWarn = nullptr;
Stats sStats;

size_t alignUp(size_t n) { return (n + (kAlignment - 1)) & ~(kAlignment - 1); }

void* dataOf(BlockHeader* b) { return reinterpret_cast<uint8_t*>(b) + sizeof(BlockHeader); }

BlockHeader* headerOf(void* data) {
  return reinterpret_cast<BlockHeader*>(reinterpret_cast<uint8_t*>(data) - sizeof(BlockHeader));
}

void warnf(const char* fmt, ...) {
  if (!sWarn) return;
  char buf[192];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  sWarn(buf);
}

// 空いている最初の十分なブロックを探す(first-fit)。余りが
// ヘッダ+アラインメント以上残るなら分割し、残りを新しい空きブロックにする。
// 分割しない場合、返すブロックのsizeは要求バイト数より大きいままになりうる
// ——呼び出し側(poolCalloc)は必ずheaderOf(p)->sizeで実サイズを読み返すこと。
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

}  // namespace

void install(uint8_t* buffer, size_t bytes, WarnFn warn) {
  sPoolBase = buffer;
  sPoolBytes = bytes;
  sWarn = warn;
  sStats = Stats{};

  sFirstBlock = reinterpret_cast<BlockHeader*>(sPoolBase);
  sFirstBlock->magic = kMagicFree;
  sFirstBlock->size = bytes - sizeof(BlockHeader);
  sFirstBlock->physNext = nullptr;
  sFirstBlock->physPrev = nullptr;
}

void* poolCalloc(size_t nmemb, size_t size) {
  size_t bytes = nmemb * size;
  sStats.callCount++;
  void* p = poolAlloc(bytes);
  if (!p) {
    sStats.failCount++;
    warnf(
        "[tls-pool] calloc FAILED for %u bytes (pool exhausted, call #%u, "
        "outstanding=%ld peak=%u)",
        (unsigned)bytes, (unsigned)sStats.callCount, sStats.currentOutstanding,
        (unsigned)sStats.peakOutstanding);
    return nullptr;
  }
  memset(p, 0, bytes);
  // poolAllocは要求バイト数ちょうどではなく、分割の余りが小さすぎる時は
  // 元の(より大きい)空きブロックをそのまま返すことがある。会計は必ず
  // ブロックヘッダの実サイズを見て、poolFree側の減算(同じくb->sizeを見る)
  // と対称にする——ここで生の`bytes`を使うと、poolFreeとの非対称で
  // sCurrentOutstandingが呼び出しのたびに少しずつ負側へドリフトする
  // (実機でcall #353147・outstanding=-1073132まで蓄積したのを実際に踏んだ。
  // docs/log/2026-08-10-tls-pool-outstanding-accounting-drift.md)。
  size_t actual = headerOf(p)->size;
  sStats.currentOutstanding += static_cast<long>(actual);
  if (sStats.currentOutstanding > static_cast<long>(sStats.peakOutstanding)) {
    sStats.peakOutstanding = static_cast<size_t>(sStats.currentOutstanding);
  }
  return p;
}

void poolFree(void* ptr) {
  if (!ptr) return;
  BlockHeader* b = headerOf(ptr);
  if (b->magic != kMagicUsed) {
    // 二重free/プール外ポインタ/破損のいずれか。プール全体を巻き込む
    // クラッシュより、ここで無視して痕跡だけ残す方が安全。
    warnf("[tls-pool] free() on non-used block (magic=%08x) — ignoring", (unsigned)b->magic);
    return;
  }
  size_t bytes = b->size;
  if (bytes > sPoolBytes) {
    // sizeが壊れている(スタック破壊・電気的ノイズ等、原因不明でも)状態で
    // マージへ進むと、隣接ブロックのヘッダを不正なオフセットで書き換え
    // 静かなヒープ破壊に発展しうる。ここで止めて実害をログだけに留める。
    warnf(
        "[tls-pool] free() with implausible size=%u (pool is %u bytes) — "
        "refusing to touch links, leaking this block",
        (unsigned)bytes, (unsigned)sPoolBytes);
    return;
  }
  b->magic = kMagicFree;
  mergeWithNext(b);
  if (b->physPrev && b->physPrev->magic == kMagicFree) {
    mergeWithNext(b->physPrev);
  }
  sStats.freeCount++;
  sStats.currentOutstanding -= static_cast<long>(bytes);
  if (sStats.currentOutstanding < 0) {
    // 対称化した今は理論上起こらないはずだが、次に何か想定外(このpoolFreeを
    // 経由しない外部からのb->size改変等)が起きた時に、call #353147まで
    // 気付けなかった前回よりずっと早く検知するための保険。
    warnf(
        "[tls-pool] accounting underflow: outstanding=%ld after freeing %u bytes "
        "(call #%u) — bookkeeping is inconsistent",
        sStats.currentOutstanding, (unsigned)bytes, (unsigned)sStats.callCount);
  }
}

Stats stats() { return sStats; }

size_t blockHeaderBytes() { return sizeof(BlockHeader); }
size_t alignment() { return kAlignment; }

bool checkInvariants(WarnFn warn) {
  bool ok = true;
  size_t total = 0;
  bool prevWasFree = false;
  for (BlockHeader* b = sFirstBlock; b != nullptr; b = b->physNext) {
    total += sizeof(BlockHeader) + b->size;

    if (b->magic != kMagicFree && b->magic != kMagicUsed) {
      if (warn) warn("[tls-pool] checkInvariants: corrupt block magic");
      ok = false;
    }
    bool isFree = (b->magic == kMagicFree);
    if (isFree && prevWasFree) {
      if (warn) warn("[tls-pool] checkInvariants: two adjacent free blocks (merge missed)");
      ok = false;
    }
    prevWasFree = isFree;

    if (b->physNext && b->physNext->physPrev != b) {
      if (warn) warn("[tls-pool] checkInvariants: physNext/physPrev link mismatch");
      ok = false;
    }
  }
  if (total != sPoolBytes) {
    if (warn) warn("[tls-pool] checkInvariants: total block size does not match pool size");
    ok = false;
  }
  return ok;
}

}  // namespace core
}  // namespace tlsmempool
