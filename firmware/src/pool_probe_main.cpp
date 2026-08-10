// バッチバッファプール(main.cppのsBatchPool)と同じサイズをmalloc()で確保できるか
// だけを確かめる使い捨てビルド。NVS未プロビジョニングのボードでも(WiFi/Uploader
// setupより前でhaltするmain.cppと違って)そのまま試せる。
// docs/log/2026-08-10-newbatch-buffer-pool-handoff.md 参照——
// dram0_0_segの静的配置制限はmalloc()には掛からない、という仮説の実機検証。
//
//   pio run -e pool-probe -t upload --upload-port <USBポート>
//   pio device monitor
#include <Arduino.h>
#include <esp_heap_caps.h>

#include "NamzWire.h"
#include "config.h"

#ifdef NAMZ_SENSOR_ADXL355
static constexpr size_t kBatchRecordBytes = 3 * sizeof(int32_t);
#else
static constexpr size_t kBatchRecordBytes = 3 * sizeof(int16_t);
#endif
static constexpr size_t kBatchQueueDepth = 4;
// main.cppと同じ式。config.hのkMaxRamBatchesを変えたら、このビルドで
// 実機再検証すること（使い捨てではなく再利用可能な診断ツールとして残す）。
static constexpr size_t kBatchPoolSlots = 1 + kBatchQueueDepth + kMaxRamBatches;
static constexpr size_t kBatchBufferBytes =
    kWireHeaderSize + kBatchSamples * kBatchRecordBytes + namzwire::kMaxTrailerBytes;

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[pool-probe] booting...");
  Serial.printf("[pool-probe] want %u slots x %u B = %u B\n", (unsigned)kBatchPoolSlots,
                (unsigned)kBatchBufferBytes, (unsigned)(kBatchPoolSlots * kBatchBufferBytes));
  Serial.printf("[pool-probe] before: free_heap=%u maxblock_internal=%u maxblock_8bit=%u\n",
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap(),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  uint8_t* pool = static_cast<uint8_t*>(malloc(kBatchPoolSlots * kBatchBufferBytes));
  Serial.printf("[pool-probe] malloc() -> %s\n", pool ? "OK" : "NULL (failed)");

  Serial.printf("[pool-probe] after:  free_heap=%u maxblock_internal=%u maxblock_8bit=%u\n",
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap(),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));

  if (pool) {
    // 実際に全域へ書き込めるか(ページフォールト的な問題が無いか)も確認しておく。
    memset(pool, 0xAA, kBatchPoolSlots * kBatchBufferBytes);
    bool ok = true;
    for (size_t i = 0; i < kBatchPoolSlots * kBatchBufferBytes; ++i) {
      if (pool[i] != 0xAA) { ok = false; break; }
    }
    Serial.printf("[pool-probe] full-range read/write check -> %s\n", ok ? "OK" : "FAILED");
  }
  Serial.println("[pool-probe] done.");
}

void loop() {
  delay(5000);
  Serial.println("[pool-probe] still alive");
}
