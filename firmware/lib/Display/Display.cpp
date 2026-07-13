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
  bgInit_ = false;  // 次のrenderで背景を塗り直させる
  paintFrame(TFT_BLACK);
}

// 画面全体を背景色で塗り、その上に静的ラベル(NAMAZU)を描き直す。
// 背景が変わったときだけ呼ぶ（毎フレーム塗るとちらつくため）。
void Display::paintFrame(uint16_t bg) {
  bg_ = bg;
  bgInit_ = true;
  tft_.fillScreen(bg);
  tft_.setTextDatum(TL_DATUM);
  tft_.setTextColor(contrastText(bg), bg);
  tft_.drawString("NAMAZU", 4, 4, 2);
}

// RGB565の輝度から、背景に対し読める文字色(黒/白)を選ぶ。
uint16_t Display::contrastText(uint16_t bg) {
  uint8_t r = ((bg >> 11) & 0x1F) << 3;
  uint8_t g = ((bg >> 5) & 0x3F) << 2;
  uint8_t b = (bg & 0x1F) << 3;
  // ITU-R BT.601 相当の重み
  uint32_t lum = (r * 299u + g * 587u + b * 114u) / 1000u;
  return lum > 140 ? TFT_BLACK : TFT_WHITE;
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
                     uint32_t backlog, const String& status, uint16_t bgColor) {
  if (!ready_) return;
  const int w = tft_.width();
  const int h = tft_.height();

  // 状態が変わったら（＝背景色が変わったら）だけ全面を塗り直す。
  // 遠目でも idle/closing/active を背景色一色で判別できるようにする狙い。
  if (!bgInit_ || bgColor != bg_) paintFrame(bgColor);
  const uint16_t bg = bg_;
  const uint16_t fg = contrastText(bg);  // 背景に応じた基準文字色

  // WiFi状態（右上）。接続時のみ緑、それ以外は背景コントラスト色で必ず見えるように。
  tft_.setTextDatum(TR_DATUM);
  tft_.setTextPadding(60);
  tft_.setTextColor(wifi ? TFT_GREEN : fg, bg);
  tft_.drawString(wifi ? "WiFi" : "no wifi", w - 4, 4, 2);

  // 計測震度（大きく中央）。severity は背景色が担うので、数字は視認優先で fg。
  char buf[24];
  snprintf(buf, sizeof(buf), "%.1f", intensity);
  tft_.setTextDatum(MC_DATUM);
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(w);
  tft_.drawString(buf, w / 2, 46, 6);  // フォント6: 大きい数字(- . 対応)

  // 震度階級（Level 表記）
  snprintf(buf, sizeof(buf), "Level %s", scaleAscii(intensity));
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(w);
  tft_.drawString(buf, w / 2, 86, 4);

  // 継続ステート
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(w);
  tft_.drawString(status, w / 2, 108, 2);

  // 下段: ピーク加速度（左） と IP/バックログ（右）
  snprintf(buf, sizeof(buf), "peak %.1f gal", peakGal);
  tft_.setTextDatum(BL_DATUM);
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(150);
  tft_.drawString(buf, 4, h - 2, 2);

  tft_.setTextDatum(BR_DATUM);
  tft_.setTextPadding(90);
  if (backlog > 0) {
    snprintf(buf, sizeof(buf), "buf:%lu", (unsigned long)backlog);
  } else if (wifi && ip.length()) {
    snprintf(buf, sizeof(buf), "%s", ip.c_str());
  } else {
    buf[0] = '\0';
  }
  tft_.setTextColor(fg, bg);
  tft_.drawString(buf, w - 4, h - 2, 2);

  tft_.setTextPadding(0);
}
