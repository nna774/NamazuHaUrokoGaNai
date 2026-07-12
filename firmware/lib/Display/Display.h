#pragma once
// 内蔵TFT(ST7789 135x240)への情報表示。TTGO T-Display 系。
// 計測震度を大きく、震度階級・継続ステート・ピーク加速度・WiFi・送信バックログを表示。

#include <Arduino.h>
#include <Preferences.h>
#include <TFT_eSPI.h>

class Display {
 public:
  void begin();

  // 画面を180度反転してNVSに保存（起動後にボタンで呼ぶ想定）。
  void toggleFlip();

  // 画面更新（2Hz程度で呼ぶ想定）。
  //  intensity   : 現在のリアルタイム計測震度
  //  peakGal     : 直近のフィルタ後合成加速度[gal]
  //  wifi        : WiFi接続済みか
  //  ip          : IPアドレス文字列（未接続なら空）
  //  backlog     : 未送信の退避バッチ数（0が正常）
  //  status      : 継続ステート文字列（"ACTIVE 12s" 等）
  //  statusColor : ステートの表示色
  void render(float intensity, float peakGal, bool wifi, const String& ip,
              uint32_t backlog, const String& status, uint16_t statusColor);

  // 震度階級のASCII表記（"0".."4","5-","5+","6-","6+","7"）。
  static const char* scaleAscii(float intensity);

 private:
  void applyRotation();  // 回転を反映し静的ラベルを描き直す

  TFT_eSPI tft_;
  Preferences prefs_;
  int rotation_ = 1;  // 1 / 3 の横向き（180度違い）
  bool ready_ = false;
};
