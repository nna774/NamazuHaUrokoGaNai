// TlsMemPoolCore(固定プールアロケータの純粋なポインタ演算部分)のホストテスト。
//
// 実機で観測した sCurrentOutstanding の負値ドリフト
// (docs/log/2026-08-10-tls-pool-outstanding-accounting-drift.md、
// call #353147で outstanding=-1073132)の再発防止が主目的。
// Arduino/mbedTLSに依存しないので素のg++でコンパイルできる。
// firmware/test/run.sh で走る。

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "TlsMemPoolCore.h"

namespace core = tlsmempool::core;

static int gFailures = 0;
static std::vector<std::string> gWarnings;

static void collectWarn(const char* msg) { gWarnings.push_back(msg); }

// "calloc FAILED"(プール枯渇)はランダムストレスで意図的に踏むので許容する。
// それ以外の警告(会計不整合・破損検知・checkInvariants失敗)はすべて異常。
static bool allWarningsBenign() {
  for (const auto& w : gWarnings) {
    if (w.find("calloc FAILED") == std::string::npos) return false;
  }
  return true;
}

static void expect(const char* name, bool cond, const std::string& detail = "") {
  if (cond) {
    printf("ok   %s\n", name);
    return;
  }
  printf("FAIL %s%s%s\n", name, detail.empty() ? "" : " -- ", detail.c_str());
  ++gFailures;
}

static void testBasicRoundTrip() {
  gWarnings.clear();
  static uint8_t pool[4096];
  core::install(pool, sizeof(pool), collectWarn);

  void* p = core::poolCalloc(1, 100);
  expect("basic: alloc succeeds", p != nullptr);
  expect("basic: outstanding > 0 after alloc", core::stats().currentOutstanding > 0);

  core::poolFree(p);
  core::Stats s = core::stats();
  expect("basic: outstanding is exactly 0 after matching free", s.currentOutstanding == 0,
         "got " + std::to_string(s.currentOutstanding));
  expect("basic: invariants hold", core::checkInvariants(collectWarn));
  expect("basic: no unexpected warnings", allWarningsBenign());
}

// 分割の余りがちょうど閾値(headerBytes+alignment)の境界ケース。この時
// poolAllocは分割をスキップし、返すブロックのsizeが要求バイト数より大きい
// まま(プール全体からヘッダ分を引いた元の空きブロックのサイズ)になる。
// 修正前はpoolCallocが生の要求バイト数だけ加算していたため、このケース1回で
// 大きくaccountingがズレた。修正後はheaderOf(p)->sizeを読み返して対称に
// 扱うので、加算/減算が必ず一致するはず。
static void testSplitSkipBoundaryKeepsAccountingSymmetric() {
  gWarnings.clear();
  const size_t headerBytes = core::blockHeaderBytes();
  const size_t align = core::alignment();
  const size_t poolBytes = 4096;
  static uint8_t pool[4096];
  core::install(pool, poolBytes, collectWarn);

  const size_t totalFree = poolBytes - headerBytes;  // install()直後の唯一の空きブロックのsize
  const size_t remainTarget = headerBytes + align;    // 分割スキップの閾値ちょうど
  const size_t need = totalFree - remainTarget;        // 上記よりheaderBytes/alignの倍数で揃う

  void* p = core::poolCalloc(1, need);
  expect("split-skip: alloc succeeds", p != nullptr);

  core::Stats afterAlloc = core::stats();
  expect("split-skip: outstanding accounts for the retained (larger) block size, not just `need`",
         afterAlloc.currentOutstanding == static_cast<long>(totalFree),
         "got " + std::to_string(afterAlloc.currentOutstanding) + " want " +
             std::to_string(totalFree));
  expect("split-skip: invariants hold right after the no-split alloc",
         core::checkInvariants(collectWarn));

  core::poolFree(p);
  core::Stats afterFree = core::stats();
  expect("split-skip: outstanding returns to exactly 0 after freeing the retained block",
         afterFree.currentOutstanding == 0, "got " + std::to_string(afterFree.currentOutstanding));
  expect("split-skip: invariants hold after free", core::checkInvariants(collectWarn));
  expect("split-skip: no unexpected warnings", allWarningsBenign());
}

// TLSハンドシェイクの出入りを模した乱数のcalloc/free列を大量に流し、
// 3つの不変条件を確認する:
//   1. 全ブロック(used+free)のsize合計+ヘッダ分 == プール全体
//   2. 隣接するfreeブロックが2つ連続で残らない(結合漏れがない)
//   3. 全部freeし終えた時点でsCurrentOutstandingがちょうど0に戻る
//      (途中経過も含め0未満に落ちない — 落ちたらpoolFree側が警告する)
static void testRandomStress() {
  gWarnings.clear();
  const size_t poolBytes = 16 * 1024;
  static uint8_t pool[16 * 1024];
  core::install(pool, poolBytes, collectWarn);

  std::srand(12345);
  std::vector<void*> live;
  constexpr int kIterations = 30000;
  for (int i = 0; i < kIterations; ++i) {
    bool doAlloc = live.empty() || (std::rand() % 100) < 60;
    if (doAlloc) {
      size_t n = 1 + (std::rand() % 2000);
      void* p = core::poolCalloc(1, n);
      if (p) live.push_back(p);  // nullptrはプール枯渇として許容(sFailCountで数えている)
    } else {
      size_t idx = static_cast<size_t>(std::rand()) % live.size();
      core::poolFree(live[idx]);
      live[idx] = live.back();
      live.pop_back();
    }
    if (i % 500 == 0) {
      expect("stress: invariants hold mid-run", core::checkInvariants(collectWarn));
    }
  }
  for (void* p : live) core::poolFree(p);
  live.clear();

  core::Stats s = core::stats();
  expect("stress: outstanding is exactly 0 once everything is freed", s.currentOutstanding == 0,
         "got " + std::to_string(s.currentOutstanding));
  expect("stress: freeCount matches successful callocs", s.freeCount == s.callCount - s.failCount,
         "freeCount=" + std::to_string(s.freeCount) +
             " callCount-failCount=" + std::to_string(s.callCount - s.failCount));
  expect("stress: invariants hold at the end", core::checkInvariants(collectWarn));
  expect("stress: no accounting/corruption warnings across the whole run", allWarningsBenign());
  printf("  (stress stats: calls=%zu frees=%zu fails=%zu peak=%zu)\n", s.callCount, s.freeCount,
         s.failCount, s.peakOutstanding);
}

int main() {
  testBasicRoundTrip();
  testSplitSkipBoundaryKeepsAccountingSymmetric();
  testRandomStress();

  if (gFailures > 0) {
    printf("%d FAILURE(S)\n", gFailures);
    return 1;
  }
  printf("all ok\n");
  return 0;
}
