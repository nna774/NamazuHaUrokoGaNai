#include "CoredumpQueue.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFiClientSecure.h>
#include <esp_core_dump.h>
#include <esp_partition.h>

#include "HmacSha256.h"

namespace coredumpqueue {

namespace {

constexpr const char* kSeqNamespace = "namzcd";
constexpr size_t kCopyChunkBytes = 512;

// 起動をまたいで単調増加する連番。ファイル名の辞書順=時系列順にするために使う
// （DeviceIdentity.cppと同じPreferences(NVS)パターン、専用namespaceで独立させる）。
uint32_t nextSequence() {
  Preferences prefs;
  uint32_t seq = 0;
  if (prefs.begin(kSeqNamespace, /*readOnly=*/false)) {
    seq = prefs.getUInt("seq", 0) + 1;
    prefs.putUInt("seq", seq);
    prefs.end();
  }
  return seq;
}

// LittleFS.open()/File::openNextFile()はArduino-ESP32のFS実装内部で
// std::make_shared<VFSFileImpl>を使っており、ヒープ逼迫時にそのnew()が失敗すると
// 未捕捉例外->abort()で機体ごと再起動しうる（batch-uplinkのUploader::
// loadOldestSpillPath()と同じ実機で確認済みの注意点）。列挙全体をtry/catchで囲み、
// 失敗は「キューが空だった」に落として呼び出し元へ伝える。
bool listQueuedFiles(const char* dir, String* names, size_t maxNames, size_t* outCount) {
  *outCount = 0;
  try {
    File root = LittleFS.open(dir);
    if (!root || !root.isDirectory()) return true;  // ディレクトリが無ければ空扱い
    for (File f = root.openNextFile(); f; f = root.openNextFile()) {
      if (f.isDirectory()) continue;
      if (*outCount < maxNames) names[*outCount] = f.name();
      (*outCount)++;
    }
  } catch (...) {
    Serial.println("[coredump] listQueuedFiles threw (heap exhausted?)");
    return false;
  }
  return true;
}

// 単純挿入ソート。リングバッファの上限程度(数件〜数十件)の小さいNを想定。
void sortNames(String* names, size_t count) {
  for (size_t i = 1; i < count; ++i) {
    String key = names[i];
    size_t j = i;
    while (j > 0 && names[j - 1] > key) {
      names[j] = names[j - 1];
      --j;
    }
    names[j] = key;
  }
}

}  // namespace

void captureIfPresent(const char* queueDir, size_t maxQueuedFiles) {
  size_t addr = 0, size = 0;
  if (esp_core_dump_image_get(&addr, &size) != ESP_OK || size == 0) return;  // 無ければ何もしない

  Serial.printf("[coredump] found hardware coredump: %u bytes\n", (unsigned)size);

  if (!LittleFS.begin(true)) {
    Serial.println("[coredump] LittleFS.begin() failed, leaving hardware coredump for next boot");
    return;
  }
  if (!LittleFS.exists(queueDir)) LittleFS.mkdir(queueDir);

  const esp_partition_t* part = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_COREDUMP, nullptr);
  if (!part) {
    Serial.println("[coredump] coredump partition not found (BUG?)");
    return;
  }

  uint32_t seq = nextSequence();
  char path[80];
  snprintf(path, sizeof(path), "%s/%010lu.bin", queueDir, (unsigned long)seq);

  File out = LittleFS.open(path, "w");
  if (!out) {
    Serial.printf("[coredump] failed to open %s for write\n", path);
    return;
  }

  uint8_t buf[kCopyChunkBytes];
  size_t copied = 0;
  bool ok = true;
  while (copied < size) {
    size_t remaining = size - copied;
    size_t chunk = remaining < kCopyChunkBytes ? remaining : kCopyChunkBytes;
    if (esp_partition_read(part, copied, buf, chunk) != ESP_OK) {
      ok = false;
      break;
    }
    if (out.write(buf, chunk) != chunk) {
      ok = false;
      break;
    }
    copied += chunk;
  }
  out.close();

  if (!ok || copied != size) {
    Serial.printf("[coredump] copy failed at %u/%u bytes, removing partial file\n",
                  (unsigned)copied, (unsigned)size);
    LittleFS.remove(path);
    return;  // ハードウェア側は消さない。次回起動でまた読める。
  }

  Serial.printf("[coredump] copied to %s (%u bytes)\n", path, (unsigned)size);
  // ローカルへの退避が確認できてから初めてハードウェア側を空ける
  // （単一image・上書き仕様の対策そのもの。docs/log/2026-08-29-
  // coredump-auto-upload-design-discussion.md）。
  esp_err_t erase_err = esp_core_dump_image_erase();
  if (erase_err != ESP_OK) {
    Serial.printf("[coredump] esp_core_dump_image_erase failed: %d\n", (int)erase_err);
  }

  // クラッシュループでspillパーティション(他の用途とも共有)を圧迫しないよう、
  // 新規追加のたびに上限を超えていないか確認し、古いものから捨てる。
  size_t count = 0;
  static constexpr size_t kMaxNames = 64;
  String names[kMaxNames];
  if (listQueuedFiles(queueDir, names, kMaxNames, &count) && count > maxQueuedFiles &&
      count <= kMaxNames) {
    sortNames(names, count);
    size_t toRemove = count - maxQueuedFiles;
    for (size_t i = 0; i < toRemove; ++i) {
      char victim[80];
      snprintf(victim, sizeof(victim), "%s/%s", queueDir, names[i].c_str());
      LittleFS.remove(victim);
      Serial.printf("[coredump] queue over limit, removed %s\n", victim);
    }
  }
}

void drainToCloud(const char* queueDir, const char* ingestUrl, const char* hmacSecret,
                   uint32_t deviceId, const char* fwVersion, const char* caCertPem,
                   uint32_t perFileTimeoutMs, uint32_t totalBudgetMs) {
  static constexpr size_t kMaxNames = 64;
  String names[kMaxNames];
  size_t count = 0;
  if (!listQueuedFiles(queueDir, names, kMaxNames, &count) || count == 0) return;
  if (count > kMaxNames) count = kMaxNames;  // 想定外に多い場合は今回分だけ処理する
  sortNames(names, count);

  String url = String(ingestUrl) + "/coredump";
  char deviceIdStr[16];
  snprintf(deviceIdStr, sizeof(deviceIdStr), "%lu", (unsigned long)deviceId);

  uint32_t startMs = millis();
  for (size_t i = 0; i < count; ++i) {
    if (millis() - startMs > totalBudgetMs) {
      Serial.println("[coredump] drainToCloud: total budget exceeded, resuming next boot");
      break;
    }

    char path[80];
    snprintf(path, sizeof(path), "%s/%s", queueDir, names[i].c_str());

    File f = LittleFS.open(path, "r");
    if (!f) continue;
    size_t size = f.size();
    // sizeは64KB(coredumpパーティション上限)を超えない。署名(hmacSha256Hex)が
    // ファイル全体を要求するためどのみちバッファへ読む必要があり、そのバッファを
    // そのままPOSTボディにも使い回す(二重読みを避ける)。setupBatchPool()より後・
    // gUploader生成より前の一時的な確保で、リクエスト完了後すぐ解放するため
    // 定常状態のヒープ断片化には影響しない。
    uint8_t* buf = static_cast<uint8_t*>(malloc(size));
    if (!buf) {
      Serial.printf("[coredump] malloc(%u) failed, retrying %s next boot\n", (unsigned)size, path);
      f.close();
      continue;
    }
    size_t got = f.read(buf, size);
    f.close();
    if (got != size) {
      Serial.printf("[coredump] short read on %s (%u/%u), retrying next boot\n", path,
                    (unsigned)got, (unsigned)size);
      free(buf);
      continue;
    }

    std::string sig = hmacSha256Hex(hmacSecret, buf, size);

    WiFiClientSecure client;
    client.setCACert(caCertPem);
    client.setHandshakeTimeout(4000);  // batch-uplinkの既定と同じ緩和策
    HTTPClient http;
    http.setTimeout(perFileTimeoutMs);
    if (!http.begin(client, url)) {
      Serial.printf("[coredump] http.begin failed for %s\n", path);
      free(buf);
      continue;
    }
    http.addHeader("X-Namz-Device", deviceIdStr);
    http.addHeader("X-Namz-Signature", sig.c_str());
    http.addHeader("X-Namz-Fw-Version", fwVersion);
    http.addHeader("Content-Type", "application/octet-stream");

    int code = http.POST(buf, size);
    http.end();
    free(buf);

    if (code >= 200 && code < 300) {
      LittleFS.remove(path);
      Serial.printf("[coredump] uploaded and removed %s (%d)\n", path, code);
    } else {
      Serial.printf("[coredump] upload failed for %s: %d, keeping for retry\n", path, code);
    }
  }
}

}  // namespace coredumpqueue
