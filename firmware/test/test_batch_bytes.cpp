// Batch + NamzWire がワイヤ形式のバイト列を変えていないことを確かめる回帰テスト。
//
// **golden は Batch を一般化する前の実装から採取した実際の出力である。**
// Batch から NAMZ の知識を抜いて lib/NamzWire へ移す作業が、送出バイト列を
// 1バイトも変えていないことを、実機を焼かずに示すためにある。
// ここが緑なら、ファームの差し替えは「同じものを別の置き場から出す」だけになる。
//
// ホストで完結する（Arduino に依存しない）。firmware/test/run.sh で走る。

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#include "Batch.h"
#include "NamzWire.h"

static int gFailures = 0;

static std::string hex(const uint8_t* p, size_t n) {
  static const char* d = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; ++i) {
    s += d[p[i] >> 4];
    s += d[p[i] & 0xf];
  }
  return s;
}

static void expectBytes(const char* name, const Batch& b, size_t wantSize,
                        const char* wantHex) {
  std::string got = hex(b.bytes(), b.size());
  if (b.size() == wantSize && got == wantHex) {
    printf("ok   %s (%zu bytes)\n", name, b.size());
    return;
  }
  printf("FAIL %s\n  want %zu %s\n  got  %zu %s\n", name, wantSize, wantHex,
         b.size(), got.c_str());
  ++gFailures;
}

static void expectEq(const char* name, long got, long want) {
  if (got == want) {
    printf("ok   %s\n", name);
    return;
  }
  printf("FAIL %s: want %ld, got %ld\n", name, want, got);
  ++gFailures;
}

// main.cpp の生産側と同じ順序で1バッチ組み立てる。
// ヘッダは「サンプルを積み終えた後」に書く点が一般化後の要（それ以前は
// sample_count が確定しない）。
static Batch* buildBatch(uint32_t capacity, uint8_t sampleFormat, uint64_t startUs,
                         uint8_t sensorType, float scale, uint32_t rateHz,
                         uint32_t deviceId, const uint16_t* temp, uint32_t nSamples,
                         const int32_t (*samples)[3]) {
  Batch* b = namzwire::newBatch(capacity, sampleFormat);
  b->begin(startUs);
  if (temp) namzwire::addTrailer(*b, kTrailerSensorTemp, temp, sizeof(*temp));
  for (uint32_t i = 0; i < nSamples; ++i) {
    namzwire::addSample(*b, samples[i][0], samples[i][1], samples[i][2]);
  }
  namzwire::fillHeader(*b, sensorType, scale, rateHz, deviceId);
  return b;
}

int main() {
  // --- S1: int16 / トレイラーあり / 満杯（IIS3DHHC 経路）---
  {
    int32_t s[5][3];
    for (int i = 0; i < 5; ++i) { s[i][0] = i*100-200; s[i][1] = i*7; s[i][2] = 16000+i; }
    uint16_t t = 0x1234;
    Batch* b = buildBatch(5, 0, 1735689600123456ULL, 1, 0.076f, 100, 1, &t, 5, s);
    expectBytes("S1 int16+trailer", *b, 68,
      "5a4d414e0201000340420eba992a0600a086010005000000e3a59b3d01000000"
      "38ff0000803e9cff0700813e00000e00823e64001500833ec8001c00843e"
      "010002003412");
    delete b;
  }

  // --- S2: int32 / トレイラーあり / 満杯（ADXL355 経路）---
  {
    int32_t s[5][3];
    for (int i = 0; i < 5; ++i) { s[i][0] = i*100000-200000; s[i][1] = i*7; s[i][2] = 260000+i; }
    uint16_t t = 0x0abc;
    Batch* b = buildBatch(5, 1, 1735689600123456ULL, 2, 0.0038f, 100, 2, &t, 5, s);
    expectBytes("S2 int32+trailer", *b, 98,
      "5a4d414e0202010340420eba992a0600a0860100050000006c09793b02000000"
      "c0f2fcff00000000a0f703006079feff07000000a1f70300000000000e000000"
      "a2f70300a086010015000000a3f70300400d03001c000000a4f70300"
      "01000200bc0a");
    delete b;
  }

  // --- S3: int16 / トレイラーなし ---
  {
    int32_t s[4][3];
    for (int i = 0; i < 4; ++i) { s[i][0] = -i; s[i][1] = i; s[i][2] = 0; }
    Batch* b = buildBatch(4, 0, 42ULL, 1, 0.076f, 100, 7, nullptr, 4, s);
    expectBytes("S3 int16 no trailer", *b, 56,
      "5a4d414e020100032a00000000000000a086010004000000e3a59b3d07000000"
      "000000000000ffff01000000feff02000000fdff03000000");
    delete b;
  }

  // --- S4: 部分埋め（count < capacity のまま送る = バックフィル時の短いバッチ）---
  {
    int32_t s[3][3] = {{1,2,3},{1,2,3},{1,2,3}};
    uint16_t t = 0xffff;
    Batch* b = buildBatch(8, 0, 999ULL, 1, 0.076f, 100, 3, &t, 3, s);
    expectBytes("S4 partial fill", *b, 56,
      "5a4d414e02010003e703000000000000a086010003000000e3a59b3d03000000"
      "010002000300010002000300010002000300"
      "01000200ffff");
    delete b;
  }

  // --- S5: int16 切り詰め経路（範囲外の値は飽和ではなく切り詰め）---
  {
    int32_t s[2][3] = {{70000,-70000,32768},{-1,1,0}};
    Batch* b = buildBatch(2, 0, 1ULL, 1, 1.0f, 100, 1, nullptr, 2, s);
    expectBytes("S5 int16 truncation", *b, 44,
      "5a4d414e020100030100000000000000a0860100020000000000803f01000000"
      "701190ee0080ffff01000000");
    delete b;
  }

  // --- S6: begin() を2回呼ぶと tail が消える ---
  {
    Batch* b = namzwire::newBatch(3, 0);
    b->begin(10ULL);
    uint16_t t = 0xdead;
    namzwire::addTrailer(*b, kTrailerSensorTemp, &t, sizeof(t));
    b->begin(20ULL);  // 積み直し: トレイラーも消える
    for (int i = 0; i < 3; ++i) namzwire::addSample(*b, i, i, i);
    namzwire::fillHeader(*b, 1, 0.076f, 100, 1);
    expectBytes("S6 begin resets tail", *b, 50,
      "5a4d414e020100031400000000000000a086010003000000e3a59b3d01000000"
      "000000000000010001000100020002000200");
    delete b;
  }

  // --- S7: 満杯後の追記とトレイラー溢れは false を返し、バイト列を汚さない ---
  {
    Batch* b = namzwire::newBatch(1, 0);
    b->begin(5ULL);
    expectEq("S7 addSample", namzwire::addSample(*b, 1, 1, 1), 1);
    expectEq("S7 full", b->isFull(), 1);
    expectEq("S7 addSample after full", namzwire::addSample(*b, 2, 2, 2), 0);
    uint8_t big[40] = {};
    expectEq("S7 trailer overflow", namzwire::addTrailer(*b, 1, big, sizeof(big)), 0);
    namzwire::fillHeader(*b, 1, 0.076f, 100, 1);
    expectBytes("S7 rejects overflow", *b, 38,
      "5a4d414e020100030500000000000000a086010001000000e3a59b3d01000000"
      "010001000100");
    delete b;
  }

  // --- 一般化で新しく可能になったこと: NAMZ と無関係な寸法でも載る ---
  // Electabuzz の GFRQ v1（64バイトヘッダ + 12バイトレコード + tail なし）を
  // Batch がそのまま扱えることを示す。共有ライブラリとして切り出す根拠。
  {
    Batch b(3, 12, 64, 0);
    b.begin(1234ULL);
    for (int i = 0; i < 3; ++i) {
      uint8_t rec[12];
      std::memset(rec, i + 1, sizeof(rec));
      b.addRecord(rec, sizeof(rec));
    }
    expectEq("GFRQ-shaped size", (long)b.size(), 64 + 3 * 12);
    expectEq("GFRQ-shaped recordCount", b.recordCount(), 3);
    expectEq("GFRQ-shaped recordsSize", (long)b.recordsSize(), 36);
    // ヘッダは呼び出し側が自由に書ける（CRC はレコード確定後に計算できる）。
    std::memset(b.headerPtr(), 0xAB, 64);
    expectEq("GFRQ-shaped header writable", b.bytes()[0], 0xAB);
    expectEq("GFRQ-shaped records not clobbered", b.records()[0], 1);
    expectEq("GFRQ-shaped wrong record length rejected",
             b.addRecord("short", 5), 0);
  }

  printf("\n%s (%d failure%s)\n", gFailures ? "FAILED" : "PASSED", gFailures,
         gFailures == 1 ? "" : "s");
  return gFailures ? 1 : 0;
}
