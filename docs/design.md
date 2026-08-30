# 設計メモ

## サンプリングとオーバーサンプリング

出力は100Hzだが、センサ(IIS3DHHC, ODR 1.1kHz固定)を**1kHz(出力の10倍)で読み、
10サンプル平均して100Hzに間引く**（`firmware/src/main.cpp`, `kOversample=10`）。

理由: 100Hz直接ポーリングだと、センサ内部帯域(数百Hz)にある50Hz超の成分が
0〜50Hzへ**エイリアシング**して混入し、一部が周期補正 sqrt(1/f) で増幅されて
静置ノイズの計測震度を押し上げる。実機の静置測定で計測震度が0.7出た原因がこれ
（スペクトルが20〜50Hz帯に偏っていた）。ボックスカー平均は簡易アンチエイリアスに
なり、白色ノイズも約√10≈3.2倍下がる。

## 計測震度アルゴリズム

気象庁の計測震度算出法を実装する。処理は2系統ある。

### FFT版（正式・オフライン / detect Lambda / tools）

1. 3成分加速度 (gal = cm/s²) を用意し、**各成分から線形トレンドを除く**
2. 各成分を FFT
3. 周波数領域でフィルタ `Y(f)` を掛ける。`Y(f)` は3つの積:
   - **周期補正**: `W_p(f) = sqrt(1/f)`
   - **ハイカット**: `W_h(f) = 1/sqrt(1 + 0.694 x² + 0.241 x⁴ + 0.0557 x⁶ + 0.009664 x⁸ + 0.00134 x¹⁰ + 0.000155 x¹²)`, `x = f/f0`, `f0 = 10 Hz`
   - **ローカット**: `W_l(f) = sqrt(1 - exp(-(f/0.5)³))`
4. 逆FFTで各成分のフィルタ後波形に戻す
5. 3成分ベクトル合成 `a(t) = sqrt(ax² + ay² + az²)`
6. `|a(t)| >= a0` となる時間の合計が 0.3 秒以上になる最大の `a0` を求める
7. `I = 2·log10(a0) + 0.94`、気象庁の丸め規則で計測震度に

f=0 成分は 0 にする（直流除去）。窓長は 60 秒が正式だが、本システムでは移動窓で近似する。

手順1のデトレンドは気象庁の定義には無い。`Y(f)` は f=0 で 0 なので直流は落ちるが
**傾きは落ちない**ため、傾斜変化や熱ドリフトを残すと、FFTの巡回畳み込みで記録の
終端と始端が繋がる際に段差ができて端がリンギングする。気象庁の手法が想定するのは
「静止に始まり静止に終わる地震記録」だが、こちらは連続ストリームを任意の位置で
切った窓を渡している。実機で静穏なのに震度2.1が出た（→ [intensity_pitfalls.md](intensity_pitfalls.md)）。
detect Lambda はさらに窓の端5秒を評価から外す（`detect_core.EDGE_GUARD_SECONDS`）。

### リアルタイム版（ファームウェア / デバイス速報）

FFTは境界を跨ぐ揺れを扱いにくく、ESP32上で60秒窓FFTを回すのも重い。
そこで時間領域IIRフィルタ（バイキュアッド直列）で `Y(f)` を近似し、ストリーミング処理する。
フィルタ状態を持ち回るので**バッチ境界問題が消える**。

- 実装は `firmware/lib/Shindo`。係数は `tools/jismo/realtime.py` と共有する設計思想
- **必ず FFT版と数値照合してから信用する**（`tools/backtest.py`）。デバイス速報はあくまで「速報」で、確定値はクラウドのFFT版が出す
- 直近60秒のフィルタ後合成加速度をリングバッファに持ち、「累計0.3秒超過値」から `I` を算出

## 生活振動の除去

扉の開閉・落下・衝突は一瞬（<0.5秒）で終わるという仮説に基づく。

- 「累計0.3秒超過値」という定義自体が単発スパイクに鈍い
- 検知条件は「リアルタイム震度 ≥ 閾値 が継続」（継続秒数=`detect_hold_seconds`、既定0.3秒）
- 閾値・継続秒数は生データでバックテストしてチューニングする（raw/の保持期間＝`raw_retention_days`ぶん手に入る。当初90日と決めたが、実際に必要な量を検証しないまま決めた数字だったため2026-08-11に60日へ短縮した。[docs/log/2026-08-11-events-accidental-deletion-protection.md](log/2026-08-11-events-accidental-deletion-protection.md)）
- 継続秒数は当初2.0秒だったが、両機のコンクリブロック固定後は生活振動が閾値振幅
  （0.603gal）にすら届かないと実データで確認できたため、2026-08-21に0.3秒へ
  引き下げた（[docs/log/2026-08-21-hold-seconds-review-after-concrete-mounting.md](log/2026-08-21-hold-seconds-review-after-concrete-mounting.md)）。
  遠地・深発・小規模な地震（八丈島東方沖M5.5、閾値超過0.40秒）を確定報で
  取りこぼしていた反省から、生活振動が閾値を超えなくなった分だけ余裕を地震側に回した形。
  再び生活振動由来の誤確定が出るようなら引き上げること。

### detect の実行頻度をバッチ長から切り離す（`NAMZ_DETECT_STRIDE_S`）

detect は raw オブジェクトの到着ごとに起動し、毎回 120秒窓（`NAMZ_DETECT_WINDOW_S`）を
読み直す。**バッチ長を短くすると「起動回数」と「1回あたりに読むオブジェクト数」が
両方増える**ので、S3 GET は長さの二乗で効く。ADXL355機を 15秒バッチにした際、
30秒機に比べて GET が約4倍になった（実測の見積り。金額は device 2台なら月数百円で、
いま構造を変える理由にはならない）。

そこで**刻みを設定で切り離してある**（`detect_stride_seconds` → `NAMZ_DETECT_STRIDE_S`）。
**値は30秒**で、15秒バッチのADXL355機を30秒バッチのIIS3DHHC機と同じ評価頻度に揃えた。
30秒バッチ機の側は全バッチが境界を跨ぐので従来と何も変わらない（`0` にすると
バッチ到着ごとの従来動作に戻る。Lambda の環境変数が無い場合のフォールバックも `0`）。
考え方は以下。

- **detect の刻みは窓の要件から決めるべきで、転送の都合で決まるのはおかしい**。
  120秒窓を15秒ごとに評価するのは8重に重複しており、30秒ごとでも4重にはなる。
  「イベントがどれかの窓に丸ごと収まる」ことさえ保証できれば刻みは粗くてよい。
- **状態を持たずに間引ける**。`floor(batch_end_us / stride) > floor(batch_start_us / stride)`
  の時だけ評価する（`detect_core.crosses_stride`）。「stride の境界を跨いだバッチだけが
  担当」という規則で、Lambda 側に前回の記憶が要らない。絶対時刻の格子で決まるので
  デバイス間でも位相が揃う。15秒バッチ・stride 30秒なら**ちょうど2回に1回**になり、
  `batch_len >= stride` なら全バッチが跨ぐので自動的に間引かれなくなる（劣化の仕方が素直）。
- 刻みを粗くする代償は**検知の遅れ**（最大 stride ぶん）であって、取りこぼしではない。
  窓が重なっている限り、揺れはいずれかの窓の内側に入る。ただし
  `EDGE_GUARD_SECONDS` を引いた実効窓長（120秒窓なら110秒）より長い刻みにはできない
  ので、`detect_core.clamp_stride` がそこで切り詰める。実際には「震度を丸ごと評価したい
  イベント長 D」に対して `stride <= 110 - D` を満たす必要があり、上限に張り付けるのは
  避けるべき。stride 30秒なら80秒以内のイベントがどこかの窓に丸ごと収まる。
- 間引くのは**窓の再評価だけ**。速報波形の永久保存（`_preserve_prompt_waveforms`）は
  S3 GET を伴わないので毎バッチ回す。
- 速報（デバイス側 `kAlertIntensity`）は別経路で即時に飛ぶので、確定報が数十秒
  遅れても通知が遅れるわけではない。**遅らせてよいのは確定側だけ**という非対称がある。

## 設置場所と向き

### 向きは自由（上下反転・壁付け・斜めすべて可）

計測震度の算出はセンサの向きに依存しない。根拠:

- JMAフィルタのFIR係数はDCゲインを厳密に0にしている（`tools/jismo/fir.py` の
  `taps -= mean`）。重力(約1g)はどの軸にどちら向きに載っても定数成分として消える。
- フィルタ後に `sqrt(x²+y²+z²)` でベクトル合成する（`tools/jismo/realtime.py`）ので、
  回転・軸入れ替え・符号反転に対して不変。気象庁の計測震度自体が3成分合成で
  水平と上下を区別しない。
- デバイス速報の発報判定もフィルタ後合成値で見ており（`firmware/src/config.h`）、
  軸依存の閾値は無い。
- IIS3DHHCはレンジ±2.5g固定なので、どの軸に1gのDCが載っても飽和しない。
  オフセット・感度の仕様も3軸同等。

影響があるのはダッシュボード波形の軸の見た目（符号・水平/上下の対応）だけ。
将来UD成分を使う機能（P波検出等）を作るなら設置向きの記録が必要になる。

### 生活振動を受けにくい設置場所

原則: **人が歩いてたわむ床から離し、建物の構造体に剛に結合する**。
生活振動の主犯は歩行による床板のローカルなたわみで、梁間中央で最大になる。

- 良い: 最下階のコンクリ土間・基礎立ち上がり直付け。木造なら1階の柱の根元、
  または柱そのものに固定。壁に貼るなら柱・間柱の真上の低い位置。
- 悪い: 石膏ボード壁面の中央（太鼓のように面外振動する）、棚・家具・メタルラックの上
  （細い支柱の固有振動が数Hz〜十数HzでJMAフィルタ通過帯域と重なり増幅器になる）、
  部屋中央の床、洗濯機・冷蔵庫・エアコン室外機・幹線道路の近く。
- 固定は剛に。デバイスが軽いので、緩い固定だとUSBケーブルの張力だけで揺れる。
  ケーブルにも遊びを持たせて途中を固定する。

理屈より計測が強い。候補場所ごとに数日置いて静穏時のノイズ床と生活振動イベントの
頻度を比較するのが確実（移設時の振動イベントは `tools/flag_event.py` で
artificial を立てる）。

## バッチのバイナリ形式

`docs/wire_format.md` を参照。要点:

- リトルエンディアン、固定長ヘッダ + `int16 × 3軸 × N`
- ヘッダに **スケール係数(LSB→mg)** と **センサ種別** を持たせ、将来のセンサ差し替え（ADXL355等）でパイプラインを壊さない
- サンプルのタイムスタンプは「バッチ開始時刻µs + index/サンプルレート」で復元

## ハードウェアの差し替え可能性

センサとESP32ボードは、どちらも「安く複数作って自宅以外に多点設置する」ことを見越して
差し替え可能に作ってある。差し替えの重さは領域ごとに大きく違う。

### センサの差し替え（軽い）

- 抽象は `firmware/lib/AccelSensor/AccelSensor.h`（`begin`/`read`/`scaleMgPerLsb`/
  `sensorType`/`sampleFormat` の5メソッド）。IIS3DHHCはその一実装
  (`firmware/lib/Iis3dhhc/`)にすぎない。
- ワイヤヘッダが `sensor_type`・`sample_format`・`scale_mg_per_lsb` を運び、
  クラウド側 `lambda/common/wire.py` は**感度もビット幅もヘッダから読む**（16/32bitすら
  固定していない）。計測震度は gal ベースなのでスケールさえ正しければパイプラインは共通。
- `config.h` の `SensorType` enum は `kSensorAdxl355=1`・`kSensorLsm6dso=2` を予約済み。
  加速度センサではない非校正の生値センサ（ピエゾ等）は別帯域(`128〜`)を使う。
  ピエゾ実験機(device_id=3)で実装済み・稼働中
  （[docs/wire_format.md](wire_format.md#sensor_type-の帯域)参照）。
- **新センサ追加で本当に要る作業**: (1) `AccelSensor` を継承したドライバを1本書く、
  (2) `config.h` にピン追加・`main.cpp` の `static Iis3dhhc gSensor(...)` の行を差し替え、
  (3) クラウドは変更ゼロ。ただし不変条件として **`tools/backtest.py` で `tools/jismo` と
  数値照合** し、**静穏時ノイズを実機で実測** してからでないと実戦投入しない。

センサ選定の指標は唯一ノイズ密度。実質これで用途が決まる（価格はおおむね性能に比例）:

| センサ | 実売目安 | ノイズ密度 | 用途の目安 |
|--------|----------|-----------|-----------|
| ADXL345 / LIS3DH | 400〜1000円 | 220〜430 µg/√Hz | 震度3以上向け（小さい揺れは埋もれる） |
| BMI160(6軸IMU) | 約300円 | 約180 µg/√Hz（実測要） | 上と同クラス。最安・割り切り多点用。I2C品が多い点に注意 |
| LSM6DSO(6軸IMU) | 約2000円 | 70 µg/√Hz | **震度1以上向け**。安価な精度枠の本命。enum予約済み |
| **IIS3DHHC（現行）** | 2420円 | 45 µg/√Hz | 震度1以上向け |
| ADXL355 | 6600円 | 25 µg/√Hz | 体に感じない揺れまで。最優秀だが高い |

多点化の指針: LCDなしの割り切り拠点は BMI160、そこそこ真面目な拠点は LSM6DSO、
高精度が要る一等地だけ IIS3DHHC/ADXL355。

### ESP32ボードの差し替え

ボード依存は3点に集約されている:

1. **TFT設定** — `platformio.ini` のTTGO T-Display(ST7789 135x240)向けフラグとピン。
2. **SPIピン** — `config.h`。無印 WROOM-32 DevKit なら 18/19/23/5 に戻す（コメントに明記）。
3. **2コア分離** — `main.cpp` で Core1=測定(100Hz)・Core0=送信/WiFi/TLS に固定。
   送信の詰まりが測定の時刻精度を乱さないための設計判断。

差し替えの重さ:

- **軽い（設定作業）**: LCDなし or 別のデュアルコアESP32（無印WROOM DevKit / ESP32-S3）。
  board差し替え + TFTフラグ削除 + ピンを戻すだけ。ただし `gDisplay` は現状 `#ifdef` で
  囲われず無条件にインスタンス化されるので、LCDを完全に消すならコンパイル時フラグを足す。
- **中程度**: 小さいLCD・別パネル。`platformio.ini` のTFT_eSPI設定と `Display.cpp` の
  描画レイアウト(135x240前提)を書き直す。
- **重い（設計に触る）**: シングルコア機（ESP32-C3/C6/S2）。Core0/Core1固定の前提が崩れ、
  測定とWiFi/TLSを1コアに同居させることになる。2コア分離で守っていた100Hzの時刻精度が
  保証できなくなるため、タスクモデルの作り直しとジッタ実測が必要。単なる設定変更ではない。
- **非推奨**: ESP8266。未送信バッチ6本(約108KB)+TLS+タスクスタックがRAMに収まらず、
  デュアルコアもない。

「安くしたい」の答えはCPUを削る（シングルコア化）ことではなく、**LCDを外して無印
デュアルコアDevKitにすること**。時刻精度を賭けてまでコアを削る価値はない。

### 多点運用時のデバイス払い出し

多点化すると `secrets.h`(必ず個体差) と `config.h`(ボード/センサで変わる) の管理が問題に
なる。`tools/provision_device.py` + `tools/devices.json` で解いた。

- **変動軸を混ぜない**。個体差(`kDeviceId`・`kHmacSecret`・場所ごとのWiFi)だけを *生成*
  対象にする。ボード差(ピン・TFT)とセンサ差は `platformio.ini` の `[env:]` が持つので、
  マニフェストは「どの env で焼くか」だけを覚える。`config.h` は生成しない
  ——形(定数・閾値)として残す。
- **HMAC秘密は両面**。`kHmacSecret` は ingest が検証するので、ファーム側(`secrets.h`)と
  サーバ側(ingest Lambda の環境変数 `NAMZ_HMAC_SECRET_<id>`)への登録を対で行う必要がある。
  片面だけだと必ずズレて認証が通らない。だから**同じ1ファイルから両方を出す**。
- **デバイスマニフェストが単一の真実**。`tools/devices.json`（鍵を含むので gitignore 対象。
  雛形は `devices.example.json`）から、(1) `secrets.h` 生成、(2) 焼くべき `[env:]` の選択、
  (3) `terraform.tfvars` の `device_hmac_secrets` 生成、の3本を導出する。

```bash
python tools/provision_device.py add --id 2 --label 2号機 --sensor adxl355  # 鍵を生成
python tools/provision_device.py secrets-h --id 2 --force                   # ファーム側
python tools/provision_device.py tfvars                                     # サーバ側
cd firmware && pio run -e "$(python ../tools/provision_device.py env --id 2)" -t upload
```

**サーバ側を先に apply してから焼く。** 逆順にすると、新しい鍵を持つデバイスの署名を
ingest が検証できず 401 になる（未登録の device_id は共通鍵 `hmac_secret` で検証される）。

YAML ではなく JSON にしたのは、`tools/` に PyYAML 依存を持ち込まないため。コメントが
書けないぶん `label` と `_comment` で補う。

## 送信の信頼性

- 送信タスクは「**2xx ackが返るまでバッチを未送信キューから消さない**」の一本のルール。失敗理由は区別しない
- 失敗時は指数バックオフ。RAMキューが溢れそうなら LittleFS へ退避、復旧後に古い順でバックフィル
- S3キーは**測定開始時刻**から決める → バックフィルは正しい時間位置に入り、ダッシュボードの欠測穴が後から埋まる。二重送信は同一キー上書きで冪等
- 退避済みのファイルは電源断で飛ばない（LittleFSは電源断耐性が設計目標）

### バッファの多段構成

`samplingTask`(Core1)が組み上げたバッチは、`gBatchQueue`(FreeRTOSキュー、深さ4、
詰まったら**最古を1本捨てて積み続ける**drop-oldest)→吸い出し専用の`batchDrainTask`
(Core0)→`Uploader`のRAMキュー(`kMaxRamBatches`本、断片化観察に応じて実機で
6→3→2と縮小してきた。現在値・経緯は`firmware/src/config.h`のコメント参照)→
溢れたら`flushToSpill()`でLittleFSへ、という順で流れ、別タスクの送信専用処理が
2xxを確認するまで送り続ける。

吸い出しと送信をあえて別タスクに分けてあるのは、**1つのタスクの中で直列に書くと
送信側のブロックで後続の吸い出し処理にプログラムカウンタが物理的に到達できなく
なる**ため——2026-08-07のdevice1で約70分間LittleFSへの退避が1本も走らなかった
障害([log/2026-08-08-device1-outage-and-deploy-drift.md](log/2026-08-08-device1-outage-and-deploy-drift.md))
の原因がこれで説明できると分かった。`Uploader`内部はmutexで保護しているが、
ネットワークI/O区間(`postBatch()`)はロックを保持しない（保持すると吸い出し側の
`enqueue()`まで巻き込みタスク分割の意味が消えるため）。

詰まった時に実際に失われるのは**RAM上にある分だけ**（`gBatchQueue`の深さぶん・
`Uploader.ram_`の送信中で宙ぶらりんな分・`samplingTask`の`cur`）。**LittleFSへ
退避済み(spill)は2xx確認後にしか消さない設計のため、パニックでも失われない。**
`newBatch()`用の固定バッファプール化は一度DRAM予算の逼迫で見送ったが、
TlsMemPool導入と静的RAM削減を経て小さいスロット数で再挑戦し、平常時の通常運転は
確認できている——ただしspillに大量の未送信分が溜まった状態からの復旧はまだ
実機検証できていない（[log/2026-08-10-batch-ram-pool.md](log/2026-08-10-batch-ram-pool.md)）。

### ネットワークI/Oのタイムアウト予算

`uploaderTask`のtask watchdog(20秒、`trigger_panic=true`)がライブラリ内部の
無制限待ちより先に発火してパニック再起動しRAM上のバッチを失う、という失敗
モードを塞ぐため、`postBatch()`が**必ず`true`/`false`で戻る**方針にしてある。
接続・TLSハンドシェイク・レスポンスヘッダ読み取りの3区間をいずれも3000ms
（`Uploader`のコンストラクタ引数、周波数モニタElectabuzzとも共有するため
呼び出し側で指定できる）に縮め、最悪合計12秒(WDT20秒に対し8秒の余裕)にして
ある。**DNS解決(`WiFi.hostByName()`)の締切は対象外のまま**——lwIP既定の
タイムアウト(14秒)に丸投げで、ここが詰まってもこの対策では防げない既知の
制限。レスポンスボディ読み取りには当初タイムアウトが無かったが、
`postBatch()`/`sendAlert()`はどちらもボディを読まないため実際には到達しない
コードパスと判明し、対処不要と分かった。

**既知の未解決問題**: 接続を使い回す(`setReuse(true)`)実装のため、前回
レスポンスのボディを読み残したまま次のヘッダ読み取りに入ると誤読しうる。
誤読時は`client_.stop()`で次回強制的に繋ぎ直され自己修復するため実害は
散発的なPOST失敗止まりと見られるが、原因調査とは独立した別バグのため
未着手のまま残っている。

検討して保留・却下した案:

- **定期再起動は不採用**——地震はいつ来るか分からず、メンテナンス目的の
  再起動と本震のタイミングが重なるリスクを許容できないため選択肢から外した
- **複数バッチを1リクエストにまとめる案**: S3レイアウト・冪等性は無変更で
  実装できると分かったが、`NamzWire`・ingest双方への変更が要るため保留
- **mbedTLS専用固定プール化**: タイムアウト予算の見直しで当面の問題は
  解消したため、予備案のまま棚上げ
- **常時spill化**: 元々は2026-08-07の70分ブロッキング障害への対症療法として
  検討し、健全時のI/O負荷・根本原因(タイムアウト無制限)を直さない点を理由に
  保留した。**別の目的（WDTパニック等の瞬時再起動でRAM上のバッチが消える窓を
  塞ぐ、タイムアウト予算では塞げない）で2026-08-30に実験実装した
  （`batchDrainTask`の`enqueue()`直後に`flushToSpill()`を追加）。健全時に常時
  LittleFS I/Oが乗るコスト自体は変わらず残っており、採用するかは実機での
  様子見込みで未確定**（[log/2026-08-30-batch-spill-before-send.md](log/2026-08-30-batch-spill-before-send.md)）

このあたりの推理の紆余曲折（複数の仮説とその反証・実機再現実験）を辿りたい
場合は[log/2026-08-08-device1-outage-and-deploy-drift.md](log/2026-08-08-device1-outage-and-deploy-drift.md)・
[log/2026-08-09-device1-outage-reboot-loop-and-data-loss.md](log/2026-08-09-device1-outage-reboot-loop-and-data-loss.md)・
[log/2026-08-29-device2-task-wdt-coredump-tls-handshake.md](log/2026-08-29-device2-task-wdt-coredump-tls-handshake.md)・
[log/2026-08-29-device2-wdt-panic-fix-direction.md](log/2026-08-29-device2-wdt-panic-fix-direction.md)・
[log/2026-08-29-device2-wdt-timeout-budget-implementation.md](log/2026-08-29-device2-wdt-timeout-budget-implementation.md)を参照。

### 可観測性

- `esp_reset_reason()`を毎バッチ`X-Namz-Reset-Reason`ヘッダで報告し、再起動が
  「パニック」「電源断」等どれだったか区別できる
- heap free/maxblockを`X-Namz-Heap-Free`/`X-Namz-Heap-Maxblock`ヘッダで報告し
  CloudWatchカスタムメトリクスに蓄積（ダッシュボードのデバイス詳細ページにも
  直近値とCloudWatchコンソールへの深リンクがある）
- ボタン長押しでの手動緊急再起動（`flushToSpill()`→`ESP.restart()`、2秒で
  確認画面・5秒で実行）。`uploaderTask`(Core0)が詰まっていても、別コアの
  `loop()`（ボタン読み取り）は生きているため効く

### coredumpの自動クラウド送信

**実装済み(2026-08-30、PR #167・#171)。** パニック時、ESP-IDFの
coredump-to-flash機構が残すバックトレースを、起動直後・WiFi接続前に
LittleFS(`/coredump/`、保持`kMaxCoredumpFiles`件のリングバッファ)へコピー
してからパーティションを消去し、`setup()`内で`gUploader`起動前に同期的に
`lambda/ingest`の`POST /coredump`へアップロードする。保存先は`data`バケットの
`coredump/`prefix(60日ライフサイクル)。ペイロードはHMAC署名計算とPOSTボディで
同じバッファを使い回す構成にした（署名にどのみちファイル全体をバッファへ
読む必要があるため）。**実機フラッシュでの動作確認・実際のパニック誘発による
アップロード確認はまだ実施していない。**
設計の経緯は[log/2026-08-29-coredump-auto-upload-design-discussion.md](log/2026-08-29-coredump-auto-upload-design-discussion.md)・
[log/2026-08-29-coredump-auto-upload-design-continued.md](log/2026-08-29-coredump-auto-upload-design-continued.md)、
実装の詳細は[log/2026-08-30-coredump-auto-upload-implementation-wrapup.md](log/2026-08-30-coredump-auto-upload-implementation-wrapup.md)参照。

## 時刻同期

- esp_sntp で起動時 + 定期同期。測定中に時刻が飛ばないよう slew 調整（`sntp_set_sync_mode(SNTP_SYNC_MODE_SMOOTH)`）
- ingest 側で受信時刻も記録し、デバイス時刻とのドリフトを監視

## S3レイアウトと保存期間

```
raw/YYYY/MM/DD/HH/<device>-<batch_start_us>.bin   # 60日でexpire（削除後30日は復旧可能）
events/<event-id>/meta.json                        # 永久
events/<event-id>/<batch_start_us>.bin             # 永久（検知周辺をコピー）
```

lifecycle は prefix 単位の expiration しかできないので、
「イベント周辺だけ永久保存」は detect 時に `events/` へコピーして実現する。

## 参考

- 気象庁: 計測震度の算出方法 https://www.data.jma.go.jp/eqev/data/kyoshin/kaisetu/calc_sindo.htm
- 功刀ら (2013): リアルタイム震度の時間領域近似フィルタ
