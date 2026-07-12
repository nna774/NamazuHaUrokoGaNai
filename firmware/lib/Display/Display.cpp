#include "Display.h"

void Display::begin() {
  prefs_.begin("namz", false);
  rotation_ = prefs_.getBool("flip", false) ? 3 : 1;
  tft_.init();
  ready_ = true;
  applyRotation();
}

void Display::applyRotation() {
  tft_.setRotation(rotation_);
  tft_.fillScreen(TFT_BLACK);
  // 静的ラベル（一度だけ描く）
  tft_.setTextDatum(TL_DATUM);
  tft_.setTextColor(TFT_CYAN, TFT_BLACK);
  tft_.drawString("NAMAZU", 4, 4, 2);
}

void Display::toggleFlip() {
  if (!ready_) return;
  rotation_ = (rotation_ == 1) ? 3 : 1;
  prefs_.putBool("flip", rotation_ == 3);
  applyRotation();
}

const char* Display::scaleAscii(float i) {
  if (i < 0.5f) return "0";
  if (i < 1.5f) return "1";
  if (i < 2.5f) return "2";
  if (i < 3.5f) return "3";
  if (i < 4.5f) return "4";
  if (i < 5.0f) return "5-";
  if (i < 5.5f) return "5+";
  if (i < 6.0f) return "6-";
  if (i < 6.5f) return "6+";
  return "7";
}

void Display::render(float intensity, float peakGal, bool wifi, const String& ip,
                     uint32_t backlog, const String& status, uint16_t statusColor) {
  if (!ready_) return;
  const int w = tft_.width();
  const int h = tft_.height();

  // WiFi状態（右上）
  tft_.setTextDatum(TR_DATUM);
  tft_.setTextPadding(60);
  tft_.setTextColor(wifi ? TFT_GREEN : TFT_RED, TFT_BLACK);
  tft_.drawString(wifi ? "WiFi" : "no wifi", w - 4, 4, 2);

  // 計測震度（大きく中央）。揺れの大きさで色を変える。
  uint16_t col = intensity < 1.5f ? TFT_GREEN
                 : intensity < 3.5f ? TFT_YELLOW
                                    : TFT_RED;
  char buf[24];
  snprintf(buf, sizeof(buf), "%.1f", intensity);
  tft_.setTextDatum(MC_DATUM);
  tft_.setTextColor(col, TFT_BLACK);
  tft_.setTextPadding(w);
  tft_.drawString(buf, w / 2, 46, 6);  // フォント6: 大きい数字(- . 対応)

  // 震度階級（Level 表記）
  snprintf(buf, sizeof(buf), "Level %s", scaleAscii(intensity));
  tft_.setTextColor(TFT_WHITE, TFT_BLACK);
  tft_.setTextPadding(w);
  tft_.drawString(buf, w / 2, 86, 4);

  // 継続ステート
  tft_.setTextColor(statusColor, TFT_BLACK);
  tft_.setTextPadding(w);
  tft_.drawString(status, w / 2, 108, 2);

  // 下段: ピーク加速度（左） と IP/バックログ（右）
  snprintf(buf, sizeof(buf), "peak %.1f gal", peakGal);
  tft_.setTextDatum(BL_DATUM);
  tft_.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft_.setTextPadding(150);
  tft_.drawString(buf, 4, h - 2, 2);

  tft_.setTextDatum(BR_DATUM);
  tft_.setTextPadding(90);
  if (backlog > 0) {
    snprintf(buf, sizeof(buf), "buf:%lu", (unsigned long)backlog);
    tft_.setTextColor(TFT_ORANGE, TFT_BLACK);
  } else if (wifi && ip.length()) {
    snprintf(buf, sizeof(buf), "%s", ip.c_str());
    tft_.setTextColor(TFT_DARKGREY, TFT_BLACK);
  } else {
    buf[0] = '\0';
  }
  tft_.drawString(buf, w - 4, h - 2, 2);

  tft_.setTextPadding(0);
}
