#pragma once
// ハード・動作パラメータの定数。秘密情報は secrets.h に置く。

#include <cstdint>

// --- シリアル ---
// クローンボードのUSB-シリアル変換は921600だと化けるため115200にする。
static constexpr uint32_t kSerialBaud = 115200;

// --- サンプリング ---
static constexpr uint32_t kSampleRateHz = 100;
static constexpr uint32_t kSamplePeriodUs = 1000000UL / kSampleRateHz;  // 出力周期 10ms

// --- オーバーサンプリング ---
// センサを出力レートの kOversample 倍(=1kHz)で読み、平均して100Hzに間引く。
// 50Hz超のエイリアシングを抑え、白色ノイズを約√kOversample 倍下げる。
static constexpr uint32_t kOversample = 10;
static constexpr uint32_t kReadPeriodUs = kSamplePeriodUs / kOversample;  // 読み周期 1ms

// --- バッチ ---
// int32 センサ(ADXL355)は 1サンプル12バイトで int16 機の倍を食う。30秒だと 36KB/本
// になり、「送信待ち1本＋充填中1本」の最小構成でも 72KB を占めて mbedTLS の
// ハンドシェイクが確保に失敗する（実機で BIGNUM - Memory allocation failed）。
// バッチ長を半分にして 18KB/本 に戻す。int16 機と同じ重さになる。
// ワイヤ形式は sample_count をヘッダに持つので、長さが変わってもクラウドは無変更。
#ifdef NAMZ_SENSOR_ADXL355
static constexpr uint32_t kBatchSeconds = 15;
#else
static constexpr uint32_t kBatchSeconds = 30;
#endif
static constexpr uint32_t kBatchSamples = kSampleRateHz * kBatchSeconds;

// --- 送信キュー / ローカルバッファ ---
// RAM上に保持する未送信バッチ数。これを超えたら LittleFS へ退避する。
// WiFi断からの復旧時、溜まったバッチを抱えたまま TLS ハンドシェイクをやることになる
// ため、ここを高くすると復旧できないまま詰まる。溢れたぶんは LittleFS へ逃げるので
// データは落ちない。
//
// この値は main.cpp の固定バッファプール(kBatchPoolSlots = 組み立て中1本 +
// gBatchQueue深さ4 + ここ)のサイズも決める——プールは静的配列で全スロットぶん
// 前もって確保するため、ここを上げるとRAM静的消費が直接その分増える
// （1本18KB強、両センサとも同じ重さ）。平常運転では ram_ がここまで埋まる
// ことはほぼ無い(Uploader::pump()が毎ループ即座に送ろうとするため)ので、
// 引き上げてもflash書き込み頻度は増えない——増えるのはバックログが実際に
// 積み上がった時にLittleFSへ逃げ始めるタイミングだけ(早まる方向)。
// 実機のRAM予算はheapテレメトリ(X-Namz-Heap-Free、CloudWatch)で見て
// 調整すること。詳細はdocs/log/2026-08-10-newbatch-buffer-pool-handoff.md。
static constexpr uint32_t kMaxRamBatches = 2;
static constexpr const char* kSpillDir = "/spill";

// --- リアルタイム検知 ---
// リアルタイム震度がこの値以上の状態が kAlertHoldSeconds 続いたらデバイス速報を出す。
static constexpr float kAlertIntensity = 0.5f;
static constexpr float kAlertHoldSeconds = 2.0f;
// 同一イベントの再通知を抑制するクールダウン。
static constexpr float kAlertCooldownSeconds = 30.0f;

// --- SPI ピン ---
// TTGO T-Display 系ボード向け。既定の 18/19/23/5 は基板上の TFT(ST7789) が
// 内部で使っておりピンヘッダに出ていないため、出力可能な空きピンへ割り当てる。
// (36/37/38/39 は入力専用なので SCK/MOSI/CS には使えない)
// 無印 WROOM-32 DevKit を使う場合は 18/19/23/5 に戻してよい。
static constexpr int kPinSck = 25;
static constexpr int kPinMiso = 27;
static constexpr int kPinMosi = 26;
static constexpr int kPinCsIis3dhhc = 33;
// ADXL355 は別CSにしておく。比較フェーズで同じバスに両方ぶら下げても衝突しない。
static constexpr int kPinCsAdxl355 = 32;
static constexpr uint32_t kSpiClockHz = 8000000;  // 8MHz（ADXL355の上限10MHzにも収まる）

// --- ボタン（TTGO T-Display 左ボタン=GPIO0。押すと画面反転）---
// GPIO0は起動時のストラップだが、起動後の押下ではブートローダに入らない。
static constexpr int kPinButtonFlip = 0;

// --- ボタン長押し: 緊急手動再起動 ---
// 家庭内ネット瞬断でdevice1が繰り返し再起動していた件（WDT panic仮説、
// docs/log/2026-08-08-wdt-panic-hypothesis.md）の暫定対策。ネットワーク越しの
// リモート再起動が届かない状況（そもそも通信不調）でも、現地でボタンだけで
// 安全に再起動できるようにする物理フェイルセーフ。
// 短押し（kRebootHoldConfirmMs未満で離す）は従来どおり画面反転のみ。
static constexpr uint32_t kRebootHoldConfirmMs = 2000;  // 確認画面へ切替 + キュー先回り退避
static constexpr uint32_t kRebootHoldTriggerMs = 5000;  // さらに押し続けたら実際に再起動

// 表示の「継続」判定（デバイス表示用。クラウドのセッションマージとは別物）。
// 60秒窓の計測震度は揺れ停止後もしばらく高いままなので、"今揺れているか"は
// 瞬時のフィルタ後合成加速度[gal]で判定する。これがしきい値を超えた最終時刻から
// kShakeHangoverMs 以内なら ACTIVE、超えて kDispCloseSeconds 経過で idle。
static constexpr float kDispActiveGal = 1.0f;
static constexpr uint32_t kShakeHangoverMs = 2000;
static constexpr uint32_t kDispCloseSeconds = 30;

// --- センサ種別（ワイヤフォーマットと一致させる）---
enum SensorType : uint8_t {
  kSensorIis3dhhc = 0,
  kSensorAdxl355 = 1,
  kSensorLsm6dso = 2,
};

// --- 時刻同期 ---
static constexpr const char* kNtpServer1 = "ntp.nict.jp";
static constexpr const char* kNtpServer2 = "pool.ntp.org";
static constexpr uint32_t kNtpResyncSeconds = 3600;  // 1時間ごと
// このオフセット[s]を超えるずれは slew では詰まらないので一度だけ step で補正する。
// これ未満はSMOOTHのslewに任せ、測定中の時刻ジャンプを避ける。水晶ドリフトは
// ppm級(1時間で数ms)なので通常この閾値には掛からない。
static constexpr uint32_t kNtpStepThresholdSeconds = 5;

// --- ビルド識別（docs/ota.md §7、pull型OTA）---
// NAMZ_FW_VERSIONはget_fw_version.py(pre extra_script)がgitの短縮hashを注入する。
// NAMZ_OTA_ENVは platformio.ini の各ハードウェアenv(esp32dev/adxl355)が定義する
// （env名そのものではなく「センサ・ボードの組」を表す。espota用の"-ota" envは
// アップロード方式が違うだけで中身は同じビルドなので同じ値になる）。
#ifndef NAMZ_FW_VERSION
#define NAMZ_FW_VERSION "unknown"
#endif
#ifndef NAMZ_OTA_ENV
#define NAMZ_OTA_ENV "unknown"
#endif
static constexpr const char* kFwVersion = NAMZ_FW_VERSION;
static constexpr const char* kOtaEnv = NAMZ_OTA_ENV;

// OTA配布物(ダッシュボードと共通のCloudFront)のTLS検証用ルートCA。
// `firmware/certs/amazon_root_ca1.pem`を`platformio.ini`の
// `board_build.embed_txtfiles`でリンクし、その先頭/終端シンボルを指す
// （main.cppで`extern`宣言する）。理由はmain.cpp側のコメント参照。

// デバイス識別情報・秘密・エンドポイントURL（旧secrets.h）はコンパイル時定数
// ではなくNVSに持つ（DeviceIdentity.h）。理由はdocs/ota.md §7「バイナリの
// 秘密情報を分離しないと成立しない」を参照——pull型OTAでenvごとに1本の
// バイナリを公開URLへ置くと、コンパイル時に焼き込んだWiFiパスワードや
// 投稿用HMAC鍵がそのまま世界に漏れる。
