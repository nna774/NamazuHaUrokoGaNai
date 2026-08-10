#pragma once
// mbedTLSの確保/解放をmbedtls_platform_set_calloc_free()で横取りし、実機での
// 呼び出し回数・サイズ・同時確保量を計測する診断ツール(docs/design.md
// 「mbedTLS専用固定プール化」案の実測フェーズ、2026-08-10)。
//
// フックはmbedTLSライブラリ全体に対してプロセス単位で1つしか差し替えられない
// （コネクション単位ではない）ため、install()以降に走る全mbedTLS呼び出し
// ——Uploaderのingest/alert接続だけでなく、将来のOTA(docs/ota.md)のTLSも——
// が対象になる。単一の固定バッファプールを1本のTLS接続専有で使う設計
// (未実装)にとっては好都合(design.mdの前提通り「TLS接続は同時に1本」なら
// 競合しない)だが、OTA実装時にこの前提が崩れないかは要確認。
//
// 実装は素通しの計測ラッパー(裏では標準calloc/freeを使う)であり、まだ
// 固定プールそのものではない——プールサイズを決める実測値を取るためだけの
// もの。確保のたびに8バイトヘッダを先頭に足してサイズを覚え、free時に
// 差し引く。単一のuploaderTaskからしか呼ばれない前提でロックは持たない
// （WiFi内部が別タスクからmbedTLSを呼ぶ経路がもしあれば数値がずれる。
// カウンタが単調に増え続けたり、outstandingが0に戻らない場面があれば
// その兆候として疑うこと）。
//
// NAMZ_TLS_ALLOC_PROBEビルドフラグでのみ使う想定（本番機のバイナリには
// 含めない、env:tls-alloc-probe参照）。

namespace tlsallocprobe {

// setup()の最も早い段階、WiFi/Uploader初期化より前に1回呼ぶ。
void install();

// 直前の呼び出し以降に確保/解放の回数が変わっていた時だけ統計をSerialへ
// 出す（変化が無ければ何もしない）。uploaderTaskのループから毎周呼ぶ想定。
void printIfChanged();

}  // namespace tlsallocprobe
