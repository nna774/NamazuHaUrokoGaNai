# 実装状況まとめ（2026-08-14 時点、ピエゾ実験機(device 3) phase1・OTA・欠測監視 稼働中）

自宅地震計 NamazuHaUrokoGaNai の、実機立ち上げ〜クラウド〜可視化まで一通り動作した記録。

## 現在の到達点

**測る → 送る → 貯める → 検知 → 通知 → 見る** の全経路が実機で動作している。

- 実機（IIS3DHHC + ESP32/TTGO T-Display）で100Hz測定、内蔵LCDに表示
- 30秒バッチをHTTPS+HMACでAWSへ送信、S3に蓄積
- デバイス速報（即時）とクラウド確定報（再解析）のハイブリッド検知
- 連続した揺れは1イベントにマージ、波形は永久保存
- Slack通知（速報/確定報、閾値で選別、イベントリンク付き）
- CloudFrontダッシュボードで波形・イベントを可視化

## デバイス一覧

払い出しの単一の真実は `tools/devices.json`（HMAC鍵等を含むためgitignore対象。
詳細は [design.md](design.md#多点運用時のデバイス払い出し) 参照）。ここでは各機の素性だけ書く。

| device_id | ラベル | センサ | 位置づけ |
|---|---|---|---|
| 1 | 湯沢-IIS3DHHC | IIS3DHHC | 実運用機（1号機）。設置場所は湯沢。下記「ハードウェア」節のスペックはこの機体のもの |
| 2 | ADXL355-2号機 | ADXL355 | 実運用機（2号機）。ADXL355機の検証・展開は [adxl355.md](adxl355.md) 参照 |
| 3 | ピエゾ実験機 | ピエゾブザー素子（保護回路経由でGPIO4、ESP32-C3スーパーミニ） | 実験機（3号機）。gal校正はせず「同時刻にバーストが立ったか」の一致だけを狙う補強検知。`sensor_type=SENSOR_TYPE_PIEZO(128)`は震度計算をスキップ（`128〜249`帯）。2026-08-12にphase1（クラウド統合）まで実機確認済み、`https://api.namazu.dark-kuins.net/devices/3`で稼働中。詳細は [piezo.md](piezo.md) 参照 |
| 4294967295 | テスト機(newBatchプール検証用、使い捨て) | なし（FakeSensor） | 物理センサ未接続。newBatchバッファプール等の結合試験専用。device_idはuint32最大値をあえて使っている（実機と衝突しないsentinel）。ファームは`env:fake-sensor`系（`FakeSensor`が`sensorType()=255`を返し、ダッシュボードには「ダミー」と表示される）。event_id・device詳細APIがdevice_idを4桁固定で見ていたバグを2件踏んで直した実績あり（`docs/log/2026-08-11-event-api-rejects-uint32-max-device-id.md`ほか） |

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
- S3 `namazu-data-*`: `raw/`は60日でexpire（バージョニング下で削除後さらに30日は復旧可能）、`events/`は永久＋削除系操作をバケットポリシーでDeny（[docs/log/2026-08-11-events-accidental-deletion-protection.md](log/2026-08-11-events-accidental-deletion-protection.md)）
- DynamoDB `namazu-events`: イベント（セッション方式でマージ）。`deletion_protection_enabled`＋PITR有効（同上）
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
| `notify_prompt_min`(k) | 1.0 | デバイス速報を通知する最小計測震度 |
| `notify_confirm_min`(l) | 0.5 | 確定報を通知する最小計測震度（k > l） |
| `slack_channel` | #nona-kanshi | 通知先チャンネル（レガシーwebhookのみ上書き可） |

小さい揺れ(0.5〜1.0)は確定報のみ、大きい揺れ(1.0以上)は速報＋確定報。

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

# ダッシュボード（S3側にCache-Controlは付けない。ブラウザ向けno-cacheは
# CloudFrontのResponse Headers Policyが付与する。CLAUDE.md参照）
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
  非該当（detect評価済み・未確定）は隠す。「全件」チェックで非該当も薄字表示。
  「機」列でどのデバイスのイベントか分かり、「機」セレクタで絞り込める（既定は全機、
  `/events?device=<id>`・URLは `#events?d=<id>`）
- **イベント詳細**: 独立画面（グラフ上部・一覧と排他でガタつかない、`#event/<id>` 直リンク）。
  グラフ下に情報パネル（発生時刻・デバイス・継続・計測震度・震度・ピーク・a0・状態・検知経路・ID）。
  縦軸レンジ選択（既定自動）
- **デバイス一覧**: 「版数」列（`X-Namz-Fw-Version`ヘッダ経由でfirmwareが毎バッチ送る、
  今動いているビルド版数）・「再起動要求」列・「OTA」列（要求中の目標版数、現在版数と
  一致すれば適用済み表示）を表示（2026-08-06、[docs/log/2026-08-06-device-status-fw-version-header.md](log/2026-08-06-device-status-fw-version-header.md)）
- API URL入力欄は config.js 設定時は非表示。重力DCを差し引いて描画
- ライブ範囲は S3コスト対策で30分上限（`/recent` の minutes を [0.1, 30] にクランプ）
- CloudFront配信は更新時に invalidation 必須

## 残タスク

- [ ] firmware README にLCD配線・表示の追記
- [ ] 数日運用して検知閾値・MERGE_GAP・通知閾値(k,l)を実データで調整
- [x] 欠測監視（データが来ないこと自体のアラート）: ingestが `namazu-devices` に
      最終受信を記録し、watchdog Lambda(EventBridge定期起動)が最終受信からの経過を
      見て欠測をSlack通知。落ちている間は1日ごとに再送、受信再開で復帰通知。
      ダッシュボードに「デバイス」タブ（`/devices`）。しきい値・間隔は変数化
      （既定: 欠測5分・再送1日・監視5分間隔）
- [x] デバイスの退役（引退）・試験機の一時停止: `namazu-devices` に `watchdog_muted`
      フラグを追加し、mute中は watchdog が完全に無視する（[docs/log/2026-08-11-watchdog-mute.md](log/2026-08-11-watchdog-mute.md)）。
      `tools/mute_device.py mute/unmute/list` で手元から操作。ingest がバッチを
      受信すると自動でunmuteされるので、`tools/devices.json` の試験機
      （fake-sensor、device 4294967295 等）のように「試験のたび繋いでは黙る」
      機体でも、mute後に再接続すれば手動unmute不要で監視が復帰する。
      ダッシュボードの「デバイス」タブもmute中は「欠測」ではなく灰色
      「監視停止」を表示し、本当に対処が要る欠測と区別する
- [x] OTA更新（詳細は [ota.md](ota.md)）: **HTTPSプル型で実装済み・device1/2両機とも
      NVS化＋実機でのpull型OTA成功確認済み**
      （[ota.md §2](ota.md#2-採用した方式-httpsプル型外出先からの更新無人運用向け)）。
      LAN内push（ArduinoOTA）も一度実装したが、母艦とデバイスが別VLANでespota転送が
      一度も届かず（ota.md §3）実用にならないまま放置されていたため、2026-08-10に
      撤去した（静的RAM約3.9KB・Flash約39KB回収）。前提としてデバイス
      識別情報・秘密をコンパイル時定数(旧secrets.h)からNVSへ移した
      （`tools/provision_device.py provision-h` → `[env:provision]`で焼く）。手元の
      `tools/request_ota.py request <id> <version>`で許可すると、デバイスが
      バッチ送信レスポンスヘッダ（リモート再起動要求と同じ経路。batch-uplink
      v1.5.0で複数ヘッダ監視に対応）で気づき`HTTPUpdate`で取得する。TLS検証は
      Amazon Root CA 1を埋め込んで`setCACert()`（既定CAバンドルは実機で機能せず、
      実際の証明書チェーンを確認して1本だけ明示指定した）。失敗時は1分バックオフ
      でリトライし、30分（既定）解消しなければwatchdogがSlack通知する。**2026-08-06、
      device1(esp32dev)・device2(adxl355)両方で実際に自己更新（旧バージョン→
      再ビルド版）まで成功し、送信も正常継続した。** ロールバック
      （`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`）は今回も見送り
- [ ] リモート再起動要求（詳細は [remote_restart.md](remote_restart.md)）: **実装済み・
      実機での動作確認はまだ**。batch-uplink v1.3.0でUploaderにレスポンスヘッダ読み取りを
      追加し、`tools/request_restart.py` で要求を立てるとデバイスが次回バッチ送信時に
      検知して安全に再起動する（v1.4.0の`flushToSpill()`で通信完了を待たず数秒で
      再起動できるようになった）
- [ ] （イベントが数万件規模になったら）DynamoDB時刻レンジGSIで本格ページング

## 済んだ主な機能

測定系検証 / オーバーサンプリング / クラウド全構築 / ハイブリッド検知 /
速報波形の永久保存 / セッションマージ / 内蔵LCD表示（反転ボタン・継続ステート）/
Slack通知（閾値・エスカレーション・チャンネル設定・イベントリンク・太字修正）/
ダッシュボード（URLルーティング・ページング・震度表示の一貫化・非該当フィルタ・
情報パネル・縦軸固定レンジ・時刻目盛り・鮮度表示・適応更新間隔・デバイスタブ）/
公開apiのセキュリティハードニング / 欠測監視（生存台帳＋watchdog＋復帰/再送通知・
退役デバイスのmute） / OTA更新（HTTPSプル型、device1/2実機確認済み） /
ADXL355 2号機の本運用化（[adxl355.md](adxl355.md)） / ピエゾ実験機(device 3)の
phase1（クラウド統合、[piezo.md](piezo.md)） / 複数機の較正・重ね表示
（[device_overlay.md](device_overlay.md)）
