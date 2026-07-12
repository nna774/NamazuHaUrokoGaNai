# 実装状況まとめ（2026-07-13 時点、通知・表示・ダッシュボード改善反映）

自宅地震計 NamazuHaUrokoGaNai の、実機立ち上げ〜クラウド〜可視化まで一通り動作した記録。

## 現在の到達点

**測る → 送る → 貯める → 検知 → 通知 → 見る** の全経路が実機で動作している。

- 実機（IIS3DHHC + ESP32/TTGO T-Display）で100Hz測定、内蔵LCDに表示
- 30秒バッチをHTTPS+HMACでAWSへ送信、S3に蓄積
- デバイス速報（即時）とクラウド確定報（再解析）のハイブリッド検知
- 連続した揺れは1イベントにマージ、波形は永久保存
- Slack通知（速報/確定報、閾値で選別、イベントリンク付き）
- CloudFrontダッシュボードで波形・イベントを可視化

## ハードウェア

| 項目 | 値 |
|------|-----|
| センサ | IIS3DHHC（±2.5g固定, 16bit, 0.076 mg/LSB, ODR 1.1kHz） |
| マイコン | ESP32-D0WDQ6（TTGO T-Display 系クローン、ST7789 135x240 内蔵） |
| センサSPI | VSPI: SCK=25 / MISO=27 / MOSI=26 / CS=33（18/19/23/5 はTFTが占有） |
| TFT | HSPI（TFT_eSPI, 18/19/5/16/23/4）。センサのVSPIと分離 |
| ボタン | GPIO0（左）で画面180度反転（NVS保存） |
| シリアル | 115200（921600は化ける）。書き込み460800 |
| ポート | `/dev/cu.usbserial-5B340453851` |

## 測定系の検証結果（実機）

| 条件 | FFT計測震度 | リアルタイム震度(速報) |
|------|:---:|:---:|
| 静置（ノイズフロア） | **-0.6（震度0）** | 0.0 |
| 叩き（単発=生活振動） | 2.0 | 0.7（アラート未満で弾く） |
| 連続揺れ（地震相当） | 3.4 | 3.3（検知・両者一致） |

基準データ: `tools/testdata/`（sample_rest / tap / shake.csv）

## クラウド構成（AWS）

- アカウント: 486414336274 / リージョン: ap-northeast-1
- Terraform管理（`terraform/`）。19リソース
- S3 `namazu-data-*`: `raw/`は90日でexpire、`events/`は永久
- DynamoDB `namazu-events`: イベント（セッション方式でマージ）
- Lambda×3: ingest / detect / api（Function URL、認証はHMAC/なし）
- CloudFront + S3 でダッシュボード配信（認証なし）

### エンドポイント

| 用途 | URL |
|------|-----|
| ダッシュボード | https://dvrrliarhuuc3.cloudfront.net |
| ingest（バッチ/`/alert`） | https://5uglpx52w3n7ktm3clomjt5rfa0nmocn.lambda-url.ap-northeast-1.on.aws |
| api（読み取り） | https://2dxg7bd6kl6xgh3rbyt4jfujna0eayau.lambda-url.ap-northeast-1.on.aws |
| CloudFront Distribution | E3C0AH1VAIC46E |

## アルゴリズム / 設計の要点

- 計測震度は `tools/jismo`（気象庁法, FFT版）が真実の源。detect Lambdaが共有
- リアルタイム震度は線形位相FIR（`firwin2`でY(f)を近似, 511tap）。ファームとPythonで同一
- **オーバーサンプリング**: センサを1kHzで読み10平均→100Hz。エイリアス除去でフロアを0.7→-0.6に改善
- **生活振動除去**: 「0.3秒累計超過」+「数秒継続」。単発スパイクは弾く
- **セッションマージ**: 新onsetが直近イベントの活動から60秒(MERGE_GAP)以内なら延長
- **送信信頼性**: 2xxまで捨てない、LittleFS退避・バックフィル、測定開始時刻ベースのS3キーで冪等・穴埋め

## 通知（検知とは別。イベントは常に記録・表示）

| 変数 | 既定 | 意味 |
|------|:---:|------|
| `notify_prompt_min`(k) | 3.0 | デバイス速報を通知する最小計測震度 |
| `notify_confirm_min`(l) | 1.5 | 確定報を通知する最小計測震度（k > l） |
| `slack_channel` | #nona-kanshi | 通知先チャンネル（レガシーwebhookのみ上書き可） |

小さい揺れ(1.5〜3.0)は確定報のみ、大きい揺れ(3.0以上)は速報＋確定報。

**エスカレーション追従**: 通知は「震度階級が新しく上がった時」に鳴る。弱く始まって
強くなるイベントでも、クラスが上がるたびに追従通知する（緊急地震速報式）。通知済み
クラスは `notified_prompt_ord` / `notified_confirm_ord` で記録し重複を防ぐ。
通知内のイベントIDはダッシュボードの該当ページ(`#event/<id>`)へのリンク。

## 震度表示の一貫化

一覧・詳細で同じ計測震度を出すため、サーバ側 `effective_intensity` に統一:
確定済みイベントは FFT の権威値(`confirmed_intensity`)、未確定は速報を含む
`max_intensity`。デバイス速報のFIRは鋭い入力で過大評価しうるため、確定後はFFT値を正とする。

## デプロイ / 更新手順

ビルド・書き込み・解析はリポジトリ直下の `.venv`（platformio + numpy + scipy）を使う。

```bash
# ファーム
cd firmware && ../.venv/bin/pio run -e esp32dev -t upload          # 通常(送信あり)
cd firmware && ../.venv/bin/pio run -e sensortest -t upload         # Phase1(シリアル出力のみ)

# Lambda（コード更新）
cd terraform && PYTHON=../.venv/bin/python ./build_lambda.sh
aws lambda update-function-code --function-name namazu-<fn> --zip-file fileb://builds/<fn>.zip
#   または terraform apply（環境変数の変更を伴う時。auto-mode分類器がブロックするので手動実行）

# ダッシュボード
cd dashboard && aws s3 cp app.js s3://namazu-dashboard-486414336274/app.js
aws cloudfront create-invalidation --distribution-id E3C0AH1VAIC46E --paths '/app.js' '/index.html'
```

秘密情報（HMAC鍵・Slack webhook）は `terraform/terraform.tfvars`（gitignore）にある。

## 立ち上げ中に見つけて直したこと

1. SPIピン競合（TFTが18/19/23/5を占有）→ 25/26/27/33へ
2. シリアル921600で化ける → 115200
3. Arduino core 2.0.x のWDT旧API対応
4. **FIRのDCゲイン残留**で重力(980gal)が漏れリアルタイム震度が跳ねた → 係数の平均を引きsum=0
5. **エイリアシング**でノイズフロアが高い → オーバーサンプリング
6. NTP同期前のバッチが1970年キーに → 同期までサンプル破棄
7. api CORSヘッダ二重付与でダッシュボードがLoad failed → Function URL側に一本化
8. 重力DCで波形が潰れて見えない → 描画時に各軸平均を差し引き
9. セッションマージのingestデプロイ漏れ / 通知env反映タイミング
10. 一覧(速報FIR値)と詳細(FFT値)で震度が食い違う → effective_intensityで統一・既存はバックフィル
11. 弱く始まり強くなるイベントの通知漏れ → 震度階級エスカレーション追従に変更
12. Slack確定報の太字が効かない（`*5.7*（` の閉じ*直後が全角括弧）→ 閉じ*の後に空白
13. 公開api の脆弱性ハードニング（下記セキュリティ節）

## セキュリティ（api/ingest は認証なし公開のためハードニング）

- `/recent` minutes を [0.1, 30] にクランプ（巨大値でS3スキャン暴走→ハング/課金を防ぐ）
- `/event` の id は `dddd-数値` 書式を強制（S3キーに直結するため）
- `/events` page/size を安全パース＆クランプ（不正値で500にしない）
- ingest は認証ヘッダの device と本文 device_id の一致を強制（別デバイス騙り防止）
- `raw_hour_prefixes` は列挙する時別prefix数に上限（多重防御）
- 割り切り: 波形データ自体は認証なしで誰でも閲覧可（個人の地震データなので公開でよい前提）

## ダッシュボード

- **ライブ波形**: 表示範囲 1/3/5/10/30分（既定1分）。縦軸は 自動/±20/±100/±500/±2000 gal
  （既定±100固定＝平常時は直線、逸脱＝異常として読める）。状態はURL `#live?m=&auto=&r=` に保持
- **自動更新の適応間隔**: 1〜3分→15秒 / 5〜10分→30秒 / 30分→60秒（窓が広いほど間引く）
- **鮮度表示**: 「最新データ N秒前」。バッチは完成後送信のため右端は常に30〜40秒過去
- **横軸の時刻目盛り**: 始点〜終端の等間隔グリッド線。10分以上は HH:MM、未満は HH:MM:SS
- **イベント一覧**: 20件ページング（`#events?p=N`）。既定は「確定＋評価待ち」のみ表示、
  非該当（detect評価済み・未確定）は隠す。「全件」チェックで非該当も薄字表示
- **イベント詳細**: 独立画面（グラフ上部・一覧と排他でガタつかない、`#event/<id>` 直リンク）。
  グラフ下に情報パネル（発生時刻・継続・計測震度・震度・ピーク・a0・状態・検知経路・ID）。
  縦軸レンジ選択（既定自動）
- API URL入力欄は config.js 設定時は非表示。重力DCを差し引いて描画
- ライブ範囲は S3コスト対策で30分上限（`/recent` の minutes を [0.1, 30] にクランプ）
- CloudFront配信は更新時に invalidation 必須

## 残タスク

- [ ] firmware README にLCD配線・表示の追記
- [ ] 数日運用して検知閾値・MERGE_GAP・通知閾値(k,l)を実データで調整
- [ ] 欠測監視（データが来ないこと自体のアラート）
- [ ] OTA更新
- [ ] （イベントが数万件規模になったら）DynamoDB時刻レンジGSIで本格ページング
- [ ] （気が向いたら）ADXL355 への差し替え

## 済んだ主な機能

測定系検証 / オーバーサンプリング / クラウド全構築 / ハイブリッド検知 /
速報波形の永久保存 / セッションマージ / 内蔵LCD表示（反転ボタン・継続ステート）/
Slack通知（閾値・エスカレーション・チャンネル設定・イベントリンク・太字修正）/
ダッシュボード（URLルーティング・ページング・震度表示の一貫化・非該当フィルタ・
情報パネル・縦軸固定レンジ・時刻目盛り・鮮度表示・適応更新間隔）/
公開apiのセキュリティハードニング
