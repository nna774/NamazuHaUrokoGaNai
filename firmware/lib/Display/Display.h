#pragma once
// 内蔵TFT(ST7789 135x240)への情報表示。TTGO T-Display 系。
// 計測震度を大きく、震度階級・継続ステート・ピーク加速度・WiFi・送信バックログを表示。

#include <Arduino.h>
#include <Preferences.h>
#include <TFT_eSPI.h>

class Display {
 public:
  // deviceId : このデバイスのID。NAMAZUの下に "id:0001" と静的表示する。
  void begin(uint32_t deviceId);

  // 画面を180度反転してNVSに保存（起動後にボタンで呼ぶ想定）。
  void toggleFlip();

  // 画面更新（2Hz程度で呼ぶ想定）。
  //  intensity : 現在のリアルタイム計測震度
  //  peakGal   : 直近のフィルタ後合成加速度[gal]
  //  wifi      : WiFi接続済みか
  //  ip        : IPアドレス文字列（未接続なら空）
  //  backlog   : 未送信バッチ数（RAMキュー+退避ファイル、0が正常）
  //  backlogAgeS : 未送信キューの最古バッチの経過秒（backlog=0なら意味を持たない）
  //  status    : 継続ステート文字列（"ACTIVE 12s" 等）
  //  bgColor   : 画面全体の背景色。継続ステートを遠目でも判別できるよう、
  //              idle/closing/active で色を変えて渡す。文字色は背景の輝度から
  //              自動でコントラスト色を選ぶので、どの背景でも文字は消えない。
  //  clock     : 上中央に出す日時文字列（"07/14 12:34:56" 等）。毎フレーム
  //              更新されるので、フリーズしていないことの目視確認にもなる。
  void render(float intensity, float peakGal, bool wifi, const char* ip,
              uint32_t backlog, uint32_t backlogAgeS, const char* status,
              uint16_t bgColor, const char* clock);

  // OTA更新中の専用画面。測定タスクが止まっている間は震度・WiFi・バックログ等の
  // 値が意味を持たない（更新中固定表示になる）ので、render()を呼ばずこちらに
  // 差し替える想定。背景色を通常のidle/closing/active(紺/橙/赤)と区別が付く紫にし、
  // 遠目でも「今は震度表示ではない」と分かるようにする。
  //  clock : render()と同じ日時文字列。凍結検知（フリーズしていれば止まって見える）
  //          を兼ねる。
  void renderOtaUpdating(const char* clock);

  // ボタン長押しによる緊急手動再起動の確認画面（config.hのkRebootHoldConfirmMs/
  // kRebootHoldTriggerMs、main.cppのloop()参照）。ボタンを離せば呼ばれなくなり
  // 通常表示に戻る（キャンセルはmain.cpp側の責務、この関数自体には無い）。
  //  clock         : render()と同じ日時文字列（凍結検知を兼ねる）。
  //  confirmed     : trueなら再起動確定後（Core0がキュー退避完了を待っている間）。
  //  remainSeconds : confirmed=falseの間、あと何秒押し続けたら再起動するか。
  void renderRebootHold(const char* clock, bool confirmed, uint32_t remainSeconds);

  // 震度階級のASCII表記（"0".."4","5-","5+","6-","6+","7"）。
  static const char* scaleAscii(float intensity);

  // 背景色に対して十分コントラストの付く文字色（黒 or 白）を返す。
  static uint16_t contrastText(uint16_t bg);

 private:
  void applyRotation();  // 回転を反映し静的ラベルを描き直す
  void paintFrame(uint16_t bg);  // 画面全体を塗り、静的ラベルを描き直す

  TFT_eSPI tft_;
  Preferences prefs_;
  int rotation_ = 1;        // 1 / 3 の横向き（180度違い）
  bool ready_ = false;
  uint16_t bg_ = 0;         // 現在の背景色
  bool bgInit_ = false;     // 背景を一度でも塗ったか（回転時にリセット）
  // 前回描いた震度階級（変化時のみ描き直してちらつき回避）。scaleAscii()の
  // 返り値は最長2文字("5-"等)+終端なので3で足りるが、余裕を見て4。
  char lastClass_[4] = "";
  uint32_t deviceId_ = 0;   // NAMAZUの下に出すデバイスID
  // renderRebootHold: confirmed=falseとtrueでは背景色(黄)が同じまま行数・Y座標が
  // 変わるため、bg色不変で背景の塗り直しを省くと前のレイアウトの残像が残る。
  // confirmed=trueへ切り替わった最初の1回だけ強制的に塗り直すためのフラグ。
  bool rebootHoldConfirmedShown_ = false;
};
