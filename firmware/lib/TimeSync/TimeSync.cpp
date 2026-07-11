#include "TimeSync.h"

#include <sys/time.h>

#include "esp_sntp.h"

namespace timesync {

void begin(const char* server1, const char* server2) {
  // slew(なめらか)同期。ステップ補正で時刻が飛ぶのを避ける。
  esp_sntp_setoperatingmode(ESP_SNTP_OPMODE_POLL);
  sntp_set_sync_mode(SNTP_SYNC_MODE_SMOOTH);
  esp_sntp_setservername(0, server1);
  esp_sntp_setservername(1, server2);
  esp_sntp_init();
}

bool isSynced() {
  return sntp_get_sync_status() == SNTP_SYNC_STATUS_COMPLETED ||
         time(nullptr) > 1700000000;  // 2023-11以降なら同期済とみなす
}

uint64_t nowUs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return static_cast<uint64_t>(tv.tv_sec) * 1000000ULL + tv.tv_usec;
}

}  // namespace timesync
