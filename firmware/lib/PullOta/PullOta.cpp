#include "PullOta.h"

#include <HTTPClient.h>
#include <Update.h>
#include <esp_task_wdt.h>

namespace pullota {

namespace {

bool fail(HTTPClient& http, String& err, const String& reason) {
  if (Update.isRunning()) Update.abort();
  http.end();
  err = reason;
  return false;
}

}  // namespace

bool fetchAndWrite(WiFiClientSecure& client, const char* url, String& err) {
  const uint32_t startMs = millis();
  HTTPClient http;
  // HTTP/1.0にしてchunked転送を避ける(Content-Lengthの分だけ読めば終わる)。
  http.useHTTP10(true);
  http.setReuse(false);
  http.addHeader("Cache-Control", "no-cache");
  if (!http.begin(client, url)) return fail(http, err, "begin failed");

  esp_task_wdt_reset();
  int code = http.GET();
  esp_task_wdt_reset();
  if (code != HTTP_CODE_OK) {
    return fail(http, err, String("HTTP ") + code + " " + HTTPClient::errorToString(code));
  }
  int total = http.getSize();
  if (total <= 0) return fail(http, err, "no Content-Length");
  if (!Update.begin(static_cast<size_t>(total), U_FLASH)) {
    return fail(http, err, String("Update.begin: ") + Update.errorString());
  }

  WiFiClient* stream = http.getStreamPtr();
  static uint8_t buf[1024];
  int written = 0;
  int nextLog = 0;
  uint32_t lastDataMs = millis();
  while (written < total) {
    esp_task_wdt_reset();
    uint32_t now = millis();
    if (now - startMs > kOverallTimeoutMs) {
      return fail(http, err, String("overall timeout at ") + written + "/" + total);
    }
    int avail = stream->available();
    if (avail > 0) {
      size_t want = min(static_cast<size_t>(avail), sizeof(buf));
      want = min(want, static_cast<size_t>(total - written));
      int n = stream->read(buf, want);
      if (n <= 0) return fail(http, err, String("read error at ") + written + "/" + total);
      if (Update.write(buf, n) != static_cast<size_t>(n)) {
        return fail(http, err, String("Update.write: ") + Update.errorString());
      }
      written += n;
      lastDataMs = millis();
      if (written >= nextLog) {
        Serial.printf("[ota-pull] %d/%d bytes (%lu ms)\n", written, total,
                      (unsigned long)(millis() - startMs));
        nextLog += 256 * 1024;
      }
      continue;
    }
    if (!stream->connected()) {
      return fail(http, err, String("connection closed at ") + written + "/" + total);
    }
    if (now - lastDataMs > kStallTimeoutMs) {
      return fail(http, err, String("stalled at ") + written + "/" + total);
    }
    delay(5);
  }

  esp_task_wdt_reset();
  // 書き込んだイメージを検証し、起動パーティションを切り替える。
  if (!Update.end()) return fail(http, err, String("Update.end: ") + Update.errorString());
  http.end();
  Serial.printf("[ota-pull] %d bytes in %lu ms\n", total, (unsigned long)(millis() - startMs));
  return true;
}

}  // namespace pullota
