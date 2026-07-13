# NamazuHaUrokoGaNai

自宅地震計システム。IIS3DHHC 加速度センサ + ESP32 で 100Hz サンプリングし、
気象庁の計測震度算出法でリアルタイムに揺れを評価する。24時間365日稼働を目標とする。

Qiita記事「地震観測用加速度センサ5種の性能比較」
(https://qiita.com/compo031/items/e62d0a0e1425c5e1efe8) がきっかけ。

## 全体像

```
[IIS3DHHC] --SPI--> [ESP32]
                      ├─ 測定タスク(Core1): 100Hzポーリング → リングバッファ
                      ├─ 検知タスク: リアルタイム震度を常時計算 → 閾値超えで即時アラート
                      └─ 送信タスク(Core0): 30秒バッチPOST / NTP / ローカル退避・バックフィル
                            │ HTTPS (Lambda Function URL, HMAC認証)
                            v
[ingest Lambda] ─→ S3 raw/YYYY/MM/DD/HH/*.bin  (90日でexpire)
       │ (非同期起動)
       v
[detect Lambda] ─ 直近数分を再計算・検証
       ├─→ DynamoDB events（重複排除）
       ├─→ S3 events/<id>/ へ波形コピー（永久保存）
       └─→ Slack 通知（Notifier差し替え可能）

[dashboard] S3+CloudFront 静的SPA ←→ [api Lambda]
```

## ディレクトリ

| dir | 内容 |
|-----|------|
| `firmware/`  | ESP32 ファームウェア (PlatformIO / Arduino core) |
| `lambda/`    | ingest / detect / api の Lambda (Python) |
| `terraform/` | AWS リソース定義 |
| `dashboard/` | 波形・イベント可視化 SPA |
| `tools/`     | シリアルキャプチャ・震度計算・バックテスト (Python) |
| `docs/`      | 設計メモ |

計測震度の算出ロジックは `tools/jismo/` を単一の真実として持ち、
detect Lambda はこれを共有する。ファームウェアの C++ 実装(`firmware/lib/Shindo`)は
これに対して数値照合してから使う。

## 実装フェーズ

1. **センサ検証** — SPIドライバ + 100Hzサンプリング + シリアル出力。静置ノイズが計測震度0近傍か確認 (`tools/`)
2. **クラウドingest** — Terraform で S3/ingest Lambda、ファームで30秒バッチ送信・リトライ・バックフィル
3. **検知・通知** — デバイス速報 + クラウド確定報のハイブリッド、Slack通知、イベント波形の永久保存
4. **ダッシュボード** — 直近n分の波形とイベントブラウザ
5. **運用強化** — OTA、欠測監視、生活振動チューニング

詳細は [docs/design.md](docs/design.md) と [plan.md](plan.md) を参照。
リポジトリの歩き方（各ドキュメントの索引・運用手順）は [CLAUDE.md](CLAUDE.md) にまとめてある。

## ライセンス

MIT (see [LICENSE](LICENSE))
