#include "Display.h"

#include "ClassFont.h"

void Display::begin(uint32_t deviceId) {
  deviceId_ = deviceId;
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
  lastClass_ = "";  // 全面を塗るので中央の震度階級も次のrenderで描き直させる
  tft_.fillScreen(bg);
  tft_.setTextDatum(TL_DATUM);
  tft_.setTextColor(contrastText(bg), bg);
  tft_.drawString("NAMAZU", 4, 4, 2);
  // デバイスID・日時は毎フレーム描く側(render)に任せる。中央の大きな震度は
  // 全幅パディングで消去するため、その帯に重なる左上のIDは震度の後に描く。
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
                     uint32_t backlog, const String& status, uint16_t bgColor,
                     const String& clock) {
  if (!ready_) return;
  const int w = tft_.width();
  const int h = tft_.height();

  // 状態が変わったら（＝背景色が変わったら）だけ全面を塗り直す。
  // 遠目でも idle/closing/active を背景色一色で判別できるようにする狙い。
  if (!bgInit_ || bgColor != bg_) paintFrame(bgColor);
  const uint16_t bg = bg_;
  const uint16_t fg = contrastText(bg);  // 背景に応じた基準文字色

  char buf[24];

  // 日時（上中央）。毎フレーム更新されるのでフリーズ検知にもなる。
  // NAMAZU(左)とWiFi(右)の間に収めるため font1 を使う。
  tft_.setTextDatum(TC_DATUM);
  tft_.setTextPadding(120);
  tft_.setTextColor(fg, bg);
  tft_.drawString(clock, w / 2, 6, 1);

  // WiFi状態（右上）。接続時のみ緑、それ以外は背景コントラスト色で必ず見えるように。
  tft_.setTextDatum(TR_DATUM);
  tft_.setTextPadding(60);
  tft_.setTextColor(wifi ? TFT_GREEN : fg, bg);
  tft_.drawString(wifi ? "WiFi" : "no wifi", w - 4, 4, 2);

  // 震度階級（大きく中央）。severity は背景色が担うので文字は視認優先で fg。
  // 内蔵フォントは大きな '+' を持たないため、0-9/+/- だけを収めた専用の
  // ClassFont(数字80px、tools/gen_class_font.py で生成)を使う。free font は
  // 「背景塗り→透過描画」の二段描きで毎フレーム描くとちらつくので、
  // 文字列が変わったときだけ描き直す（背景変化時は paintFrame が消す）。
  const int classY = 60;  // 中央基準のY
  const char* cls = scaleAscii(intensity);
  // MC_DATUM のベースラインは classY + ascent/2。字面はそこから1px下まで出る。
  const int classBottom = classY + kClassFontAscent / 2 + 2;
  if (lastClass_ != cls) {
    lastClass_ = cls;
    tft_.setFreeFont(&ClassFont);
    tft_.setTextDatum(MC_DATUM);
    tft_.setTextColor(fg, bg);
    tft_.setTextPadding(w);  // 全幅パディングでこの帯を一度消す
    tft_.drawString(cls, w / 2, classY, 1);
    tft_.setTextFont(1);  // font1(時計)がClassFontにならないよう内蔵に戻す
  }

  // 精密な計測震度（右下に小さく添える）。階級の全幅パディングの後に描くので残る。
  // 右寄せ・下寄せで階級の下端にそろえる。
  snprintf(buf, sizeof(buf), "%.1f", intensity);
  tft_.setTextDatum(BR_DATUM);
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(64);
  tft_.drawString(buf, w - 6, classBottom, 4);

  // デバイスID（NAMAZUの下・左上）。中央の階級が全幅パディングでこの帯を
  // 消去するため、階級の後に描いて残す。左寄せなので中央とは重ならない。
  snprintf(buf, sizeof(buf), "id:%04lu", (unsigned long)deviceId_);
  tft_.setTextDatum(TL_DATUM);
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(70);
  tft_.drawString(buf, 4, 24, 2);

  // 継続ステート
  tft_.setTextDatum(MC_DATUM);
  tft_.setTextColor(fg, bg);
  tft_.setTextPadding(w);
  tft_.drawString(status, w / 2, 110, 2);

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
