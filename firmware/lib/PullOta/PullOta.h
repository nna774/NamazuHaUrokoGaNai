#pragma once
// pull型OTAのファーム本体を取得して書き込む(docs/ota.md §2)。
//
// HTTPUpdateを使わない。Update.writeStream()は4KBセクタが埋まるまで戻らず、
// その間はonProgressも呼ばれないため、受信が細切れ・停滞するとタスクWDT(20秒)が
// 先に発火する(docs/log/2026-11-14-ota-pull-own-loop.md)。

#include <Arduino.h>
#include <WiFiClientSecure.h>

namespace pullota {

// 受信が途絶えたとみなして諦めるまでの時間。
constexpr uint32_t kStallTimeoutMs = 15000;
// 取得全体の締切。測定を止めている時間の上限でもある。
constexpr uint32_t kOverallTimeoutMs = 180000;

// clientはCA・ハンドシェイク締切を設定済みのものを渡す。
// 成功(書き込み・検証・起動パーティション切り替えまで完了)ならtrue。再起動は呼び出し側。
// 失敗時はerrに理由を入れてfalseを返す。書きかけのUpdateは中断済み。
// 呼び出しタスクがタスクWDTに登録されていれば、ループ中に養う。
bool fetchAndWrite(WiFiClientSecure& client, const char* url, String& err);

}  // namespace pullota
