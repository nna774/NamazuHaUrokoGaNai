#pragma once
// デバイス固有の識別情報・秘密・エンドポイントURL。
//
// コンパイル時定数(旧secrets.h)としては埋め込まず、NVS(Preferences)に持つ。
// 理由(docs/ota.md §7「バイナリの秘密情報を分離しないと成立しない」):
// pull型OTAで env ごとに1本のバイナリを公開URLへ置く設計は、WiFiパスワードや
// 投稿用HMAC鍵がバイナリに平文で焼き込まれていると成立しない。OTAはappパー
// ティションのみを書き換えNVSには触らないため、ここに置けばOTAをまたいで
// 保持され、かつ公開バイナリ自体には何も残らない。
//
// 書き込みは初回USB書き込み時、専用の provision ビルド(firmware/src/provision_main.cpp)
// から1回だけ行う（tools/provision_device.py provision-h参照）。

#include <Arduino.h>

struct DeviceIdentity {
  uint32_t deviceId = 0;
  String wifiSsid;
  String wifiPass;
  String hmacSecret;
  String otaPassword;
  // エンドポイントURL自体は秘密ではないが、デバイス個体差ではなくデプロイ差
  // （手元の devices.json manifest）に属するので、同じ経路でNVSへ持つ。
  String ingestUrl;
  String alertUrl;
  String apiUrl;
  String otaBaseUrl;
};

// NVSから読む。deviceId/wifiSsid/hmacSecret のいずれかが空なら未プロビジョニング
// とみなし false を返す（呼び出し側は起動を止めるべき——空文字列のまま
// WiFi.begin()等を呼ぶと不定動作になる）。
bool loadDeviceIdentity(DeviceIdentity& out);

// NVSへ書く。provision専用ビルドから呼ぶ。
bool saveDeviceIdentity(const DeviceIdentity& in);
