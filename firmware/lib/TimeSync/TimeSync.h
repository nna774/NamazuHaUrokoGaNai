#pragma once
// NTP時刻同期。測定中に時刻が飛ばないよう smooth(slew) 同期を使う。

#include <cstdint>

namespace timesync {

// SNTPを開始（smoothモード）。WiFi接続後に呼ぶ。
void begin(const char* server1, const char* server2);

// 一度でも時刻同期できたか。
bool isSynced();

// 現在のUNIX時刻[us]。
uint64_t nowUs();

}  // namespace timesync
