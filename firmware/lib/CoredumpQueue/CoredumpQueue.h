#pragma once
// 起動時にESP-IDFのcoredump-to-flashパーティションに残っている中身をLittleFSへ
// 退避してからクラウドへ送る一連の処理
// (docs/log/2026-08-29-coredump-auto-upload-plan.md)。
//
// coredumpパーティションは単一image・次のパニックで上書きされる仕様
// (espcoredumpの esp_core_dump_image_get() のAPI設計から確認済み)。
// captureIfPresent() を起動直後・WiFi接続前に呼んでLittleFSのリングバッファへ
// コピーし、ハードウェア側を空けることで、連続クラッシュでも証拠が残るように
// する。drainToCloud() はWiFi接続後に呼び、キューを古い順に1件ずつクラウドへ
// 送って200が返ったものだけ消す（それ以外は残して次回起動時に再試行する）。
//
// 秘密情報(WiFiパス・HMAC鍵)が写り込んでいる可能性がある前提で扱うため、
// 送信先はNVSに保存済みのingest URLに"/coredump"を足しただけで、新しい
// プロビジョニング項目は増やさない。Uploader(batch-uplink)は経由させない
// ——batch-uplinkは測定対象非依存という設計原則があり、coredumpの送信先・
// 形式はnamazu固有のため。

#include <cstddef>
#include <cstdint>

namespace coredumpqueue {

// 起動直後・WiFi接続前に1回呼ぶ。ネットワーク非依存のローカルflash操作のみ。
// ハードウェアのcoredumpパーティションに中身があればLittleFS(queueDir)へコピーし、
// コピーが確認できたら esp_core_dump_image_erase() でハードウェア側を空ける
// （コピーに失敗した場合はハードウェア側を消さず、次回起動での再挑戦に委ねる）。
// queueDir内のファイル数がmaxQueuedFilesを超えたら古いものから削除する
// （クラッシュループでspillパーティションを圧迫しないための上限）。
// LittleFS自体のマウント(LittleFS.begin(true))もここで行う
// （現状Uploader::begin()が唯一のマウント元だったが、それより早く動く必要が
// あるため独立して呼ぶ。二重mount自体は無害な想定——実機で確認すること）。
void captureIfPresent(const char* queueDir, size_t maxQueuedFiles);

// WiFi接続後、gUploader生成より前に1回呼ぶ。queueDir内のファイルを古い順に
// 1件ずつ ingestUrl + "/coredump" へPOSTし、200系が返ったものだけ削除する。
// 署名はbatch-uplinkのhmacSha256Hex()と同じHMAC-SHA256で、ファイル全体を
// バッファへ読んでから計算する(パーティションが64KB上限のため単発mallocの
// 上限も64KBに収まる。setupBatchPool()より後・gUploader生成より前というタイミングで
// 一時的に確保しリクエスト完了後すぐ解放するため、定常状態のヒープには残らない)。
// 1件あたりperFileTimeoutMs・全体totalBudgetMsの上限を超えたら打ち切る
// （WDTには頼らない、millis()ベースの自前デッドライン）。
// TLS接続はこの関数の中でしか張らない——呼び出し時点でTlsMemPoolの
// 「単一TLS接続前提」を満たせるよう、必ずgUploader生成より前に呼ぶこと。
void drainToCloud(const char* queueDir, const char* ingestUrl, const char* hmacSecret,
                   uint32_t deviceId, const char* fwVersion, const char* caCertPem,
                   uint32_t perFileTimeoutMs, uint32_t totalBudgetMs);

}  // namespace coredumpqueue
