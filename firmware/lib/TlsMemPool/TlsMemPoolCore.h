#pragma once
// TlsMemPoolの固定プールアロケータのうち、Arduino/mbedTLSに依存しない純粋な
// ポインタ演算部分。ESP32上のTlsMemPool.cppとホストg++の
// firmware/test/test_tls_mem_pool.cppの両方から同じロジックを使う
// (firmware/test/run.shがホスト側を実行する)。
//
// 呼び出し元(install)が単一スレッド/単一タスクからしか呼ばない前提で
// ロックは持たない。この前提はTlsMemPool.h側のコメントを参照。

#include <cstddef>
#include <cstdint>

namespace tlsmempool {
namespace core {

struct Stats {
  size_t callCount = 0;
  size_t freeCount = 0;
  size_t failCount = 0;
  size_t peakOutstanding = 0;
  long currentOutstanding = 0;
};

// 診断メッセージ(確保失敗・想定外のfree・会計不整合)を受け取るコールバック。
// nullptr可(サイレントに動く)。メッセージは既にフォーマット済みの1行。
using WarnFn = void (*)(const char* msg);

// buffer[0, bytes)をプールとして初期化する。所有権(malloc/freeやvectorの
// 寿命管理)は呼び出し側の責務。
void install(uint8_t* buffer, size_t bytes, WarnFn warn);

void* poolCalloc(size_t nmemb, size_t size);
void poolFree(void* ptr);

Stats stats();

// テスト用: BlockHeader1個のバイト数とアラインメント境界。プラットフォーム
// 依存(32bit ESP32と64bitホストでポインタサイズが違う)なので、境界ケースを
// 構成するテストコードはこれを使って計算する(リテラルを埋め込まない)。
size_t blockHeaderBytes();
size_t alignment();

// テスト・診断用: 全ブロック(used+free)のsize合計+ヘッダ分がプール全体と
// 一致するか、隣接するfreeブロックが2つ連続で残っていないか(結合漏れ)、
// physNext/physPrevの相互リンクが一致しているかを検査する。
// O(ブロック数)なので、本番のホットパス(poolFree等)からは呼ばない。
bool checkInvariants(WarnFn warn);

}  // namespace core
}  // namespace tlsmempool
