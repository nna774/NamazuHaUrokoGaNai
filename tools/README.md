# tools — 計測震度アルゴリズムと解析スクリプト

計測震度の算出ロジックの**単一の真実の源**。detect Lambda はこの `jismo/` を共有し、
ファームウェアの C++ 実装はここに対して数値照合してから使う。

## セットアップ

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## `jismo/` パッケージ

| module | 内容 |
|--------|------|
| `filters.py`  | 気象庁フィルタ Y(f)（周期補正・ハイカット・ローカット） |
| `jma_fft.py`  | FFTベースの正式な計測震度算出 |
| `fir.py`      | Y(f) を近似する線形位相FIRの設計・C配列出力 |
| `realtime.py` | FIRによるストリーミング震度（ファーム実装のリファレンス） |
| `rounding.py` | 気象庁の丸め規則・震度階級 |

## スクリプト

```bash
# 合成波形を作ってFFT版とFIR版の震度を比較
python gen_synthetic.py --kind quake --amp 20 --seconds 90 | python backtest.py -

# 実機シリアルをCSVに保存（LSB->gal換算。--sensor か --scale の指定は必須）
python capture_serial.py --sensor iis3dhhc --port /dev/tty.usbserial-XXXX --seconds 60 > cap.csv
python backtest.py cap.csv --trace

# ファーム用のFIR係数ヘッダを生成
python gen_fir_header.py   # -> firmware/lib/Shindo/JmaFirTaps.h

# デバイス払い出し（devices.json が単一の真実。詳細は docs/design.md）
python provision_device.py list
python provision_device.py add --id 2 --label 2号機 --sensor adxl355  # HMAC鍵を生成
python provision_device.py provision-h --id 2 --force                 # NVS書き込み用(secrets_provision.h)
python provision_device.py tfvars                                     # サーバ側（tfvarsへ貼る）
python provision_device.py env --id 2                                 # 焼くenv名

# 確定イベントに人工地震（テスト等）フラグを立てる/降ろす（DynamoDBを直接更新）
export NAMZ_EVENTS_TABLE=namz-events   # or --table
python flag_event.py mark   0001-59462454        # このイベントを人工地震に
python flag_event.py mark --before 0001-59462454 # これ以前(同一デバイス)を全部
python flag_event.py mark --before 0001-59462454 --confirmed-only  # うち確定済みだけ
python flag_event.py list                        # 立っているものを一覧
```

`mark`/`unmark` は対象を一覧表示して確認を取ってから実行する（`--before` は複数件を
一気に書き換えるため特に注意）。確認を省くときは `-y`/`--yes`。

**運用の既定: 「人工地震にして」と言われたら `--confirmed-only` を付ける。** 未確定
（checked かつ未確定）のイベントは一覧の既定フィルタで元々隠れているので、人工地震
フラグを立てる意味があるのは実質確定済みだけ。非確定まで一律に付けるのは手間のわりに
効果がない。明示的に「非確定も含めて全部」と言われた時だけ `--confirmed-only` を外す。

`provision_device.py` の `devices.json` は **HMAC鍵を含むので gitignore 対象**（雛形は
`devices.example.json`）。**サーバ側を apply してから焼くこと。** 逆順だと新しい鍵の
署名を ingest が検証できず 401 になる。

`flag_event.py` は AWS 認証情報（通常の boto3 の解決）で DynamoDB を直接更新する。
フラグを立てたイベントはダッシュボードの一覧では隠れ（「全件」表示でのみ薄く出る）、
詳細で「人工地震（テスト等）」と表示される。震度や確定状態は変えない。

**`flag_event.py`/`promote_event.py`共通の注意: `/event` APIはCloudFrontで書き込み後不変を
前提に長期キャッシュしている**（確定イベントは1年相当、`terraform/custom_domain.tf`の
`aws_cloudfront_cache_policy.api_event`。キャッシュキーは`id`クエリを含むためevent_idごとに
別エントリ。詳細は
[docs/log/2026-08-23-api-cloudfront-recent-event-cache.md](../docs/log/2026-08-23-api-cloudfront-recent-event-cache.md)）。

**無効化が要るのは、既に一度でも取得された(=キャッシュされ得た)既存event_idの内容を
`flag_event.py`のnote/confirm/unconfirm/relate等で書き換えて、ダッシュボードにすぐ
反映させたい時だけ。** `promote_event.py`が新規に発行するevent_idは、書き込み前は
まだ誰にも取得され得ないので、初回フェッチ（手元での確認curl等）は無効化なしで最新の
内容を返す——新規イベント作成の直後に反射的に打つ必要はない
（実例: [docs/log/2026-08-24-cloudfront-invalidation-scope.md](../docs/log/2026-08-24-cloudfront-invalidation-scope.md)）。
迷ったら安全側に倒して打っても実害はない（無料枠内・数分で反映）が、判断に迷わないよう
上の基準で線引きする。

```bash
aws cloudfront create-invalidation \
  --distribution-id "$(cd ../terraform && terraform output -raw api_distribution_id)" \
  --paths '/event*'
```

## イベントのメモ・手動昇格（`flag_event.py note` / `promote_event.py`）

どのイベントにも自由記述メモ（`note`）を付けられる。

```bash
python flag_event.py note 0001-59507458 "令和8年熊本地震。P波到達を水平2軸で確認"
python flag_event.py note 0001-59507458 --clear   # メモ削除
```

複数デバイスで同じ地震を捉えた（あるいは片方だけ手動で `promote_event.py` した）とき、
`flag_event.py relate` でイベント同士を相互リンクできる。イベントIDは device_id ごとの
別レコードのままだが（[CLAUDE.md](../CLAUDE.md) 不変条件参照）、リンクを張ると
ダッシュボードのイベント詳細に「関連イベント（同一地震・他機）」としてリンクが出る。

```bash
python flag_event.py relate 0001-59462454 0002-59462111 0003-59462999  # 3件以上も可
python flag_event.py unrelate 0001-59462454 0002-59462111              # 指定した組だけ解除
```

**運用方針（当面）: 実際の地震で1台だけが自動検知した場合、他機は `promote_event.py` で
手動昇格させた上で `relate` で繋げる。** 全機の波形を検知時に自動でコピーする仕組みは
今は作っていない（経緯は
[docs/log/2026-08-20-relate-events-across-devices.md](../docs/log/2026-08-20-relate-events-across-devices.md)）。

速報(device_prompt)は複数機とも自動で拾えたのに、`cloud_confirmed`の継続時間条件
（`HOLD_SECONDS`、`docs/design.md`「生活振動の除去」）に届かず一覧の既定から
隠れることがある。事後解析（`detectlab.py`等）で本物の地震と判断できたら、
`promote_event.py`を使わず既存イベントのまま`confirm`で`manual`フィールドを立てて
既定表示へ昇格できる。

```bash
python flag_event.py confirm 0001-59577127 0002-59577127   # 一覧の既定表示に出す
python flag_event.py unconfirm 0001-59577127               # 取り消す
```

`promote_event.py` は、自動検知に満たない弱い揺れや振り返りたい時間帯を、raw の保持期限
（90日）で消える前に手動で events/ へ昇格（永久保存）する。`manual` フラグが立ち、一覧の
既定にも確定と同格で出る。保存区間から計測震度も計算して記録する。

```bash
export NAMZ_EVENTS_TABLE=namazu-events   # or --table
export NAMZ_BUCKET=namazu-data-XXXX      # or --bucket（既定は terraform output data_bucket）
# 2026-07-28 16:29頃を前60秒〜後300秒ぶん保存し、メモを付ける
python promote_event.py --onset "2026-07-28 16:29:00" --pre 60 --post 300 \
    --note "令和8年熊本地震" 
python promote_event.py --onset "2026-07-28 16:29:00" --dry-run   # 書き込まず内容表示
```

`--device` は既定で raw のファイル名から推定。`--dry-run` で保存内容（event_id・バッチ数・
計測震度）を確認してから実行するのが安全。書き込み系なので api(参照専用)ではなく手元から
S3/DynamoDB を直接操作する（`flag_event.py` と同じ思想）。

**`--post`は余裕を持って長めに取ること。** 揺れが収まったように見える時刻の後も、
振幅としては目立たない後続波（コーダ）がしばらく続くことがある（2026-08-23のM5.9で
`detectlab.py`の直線性一致度パネル（`--corr-win`）を使って確認したところ、STA/LTAが
下がった後もdevice間のコヒーレンスは2分近く残っていた。振幅ベースの見た目だけで
「収まった」と判断すると後半を切り捨てやすい）。迷ったら`--post 300`〜`600`程度まで
広げておく方が安全——raw保持期間内なら後から`--pre`/`--post`を広げて撮り直せるが、
保持期限を過ぎると二度と取れない。detect Lambda側の自動確定も同じ理由で
`POST_SECONDS`を600秒にしている（`docs/log/2026-08-23-event-post-window-extension.md`）。

## 複数機の傾き・相対方位較正（`calibrate_orientation.py`）

[device_overlay.md](../docs/device_overlay.md) §3.b の実装。据え付け直後に複数機を
同時に人工加振（机を叩く等）すると、各機がそれをイベントとして記録する。そのイベントIDを
渡すと、静穏区間の重力DCから**傾き**、タップ直後の水平粒子運動の主軸フィットから
**相対方位**（基準機に対してどれだけ回っているか）を出す。

```bash
export NAMZ_EVENTS_TABLE=namazu-events
export NAMZ_DEVICES_TABLE=namazu-devices

# 表示のみ（書き込みなし）。基準機は既定で最小のdevice_id
python calibrate_orientation.py 0001-59541742 0002-59541742

# namazu-devices に書き込む（確認プロンプトあり。-y で省略）
python calibrate_orientation.py 0001-59541742 0002-59541742 --write
```

出力例:

```
基準デバイス: 0001

device   tilt_deg  azimuth_deg  coherence   lag_ms  event
000001      0.854        0.000      (ref)        -  0001-59541742
000002      0.472       -7.889      0.981      -26  0002-59541742
```

- `tilt_deg` は各機独立（重力DCだけで決まる。相手の機体は不要）。
- `azimuth_deg` は基準機に対する相対値。基準機自身は定義上0。
- `coherence`（0〜1）はタップ波形の回転フィットの当てはまり具合。**0.7未満は警告が出る**
  （タップが弱い／2機が剛結できていない疑い）。実測（2026-08-09、机を叩くテスト）では
  タップ直後±0.2〜0.5秒の窓に絞ると0.98まで上がった（反響が乗る前の初動が最も素直）。
- `lag_ms` は両機の検出onset時刻の差（クロック・検出アルゴリズムの違い。方位の値自体には
  影響しない診断用の値）。
- `--write` で書き込むのは `tilt_up`（raw sensor frameでの重力方向、単位ベクトル）・
  `tilt_deg`・`azimuth_deg`・`calibration_ref_device`・`calibrated_at_us`・
  `calibration_events`（使ったイベントIDのCSV）。**毎回全体を上書きする**ので、
  据え付けを直したりデータが増えたりしたら同じコマンドを新しいイベントIDで叩けばよい。
- 3台以上を同時に叩いた場合はイベントIDを並べるだけでよい（全機が `--ref` に揃う）。
- 前提: 各イベントが `events/<id>/` に永久保存されていること（`waveform_prefix` が
  DynamoDBに記録されている。確定イベントなら detect Lambda が自動でやる）。

## ノイズに埋もれた小地震の炙り出し（`detectlab.py`）

時間波形1本では環境ノイズ（足音・ファン・交通）のRMSに埋もれて見えない弱い揺れを、
複数の視点で可視化して立ち上がり候補時刻を出す**解析ビュー**（検出器ではない。
自動検知は detect Lambda の担当）。データは `lambda/common` 経由でS3(`raw/`)を
フルレート直読みする（APIは30秒超でエンベロープに間引かれスペクトル解析に使えないため）。

### なぜ見えるのか（5つのパネル）

弱い地震は「特定の周波数帯に集中した、3軸に相関する過渡」だ。振幅がノイズに埋もれても、
次の視点なら浮かび上がる。図は上から順に:

1. **生波形**（重力DC除去）… まず「見えない」ことの確認
2. **バンドパス波形** … 帯域外ノイズを削ぎ、過渡を浮かせる
3. **スペクトログラム**（時間×周波数）… 過渡が縦のエネルギー筋として立つ
4. **STA/LTA比**（短期/長期エネルギー比。地震観測網のトリガと同じ原理）… 過渡だけがピーク。
   閾値超えを onset 候補として時刻出力する
5. **3軸直線性**（粒子運動の偏光）… 地震の実体波は震源方向に沿った直線偏光で1に近づき、
   ランダムな等方ノイズは0.5前後に留まる。過渡が「地震らしいか」の傍証

### 使い方

```bash
cd tools && . ../.venv/bin/activate

# 基本: ある時刻(JST)を中心に前後N分をS3から取って解析
python detectlab.py --at "2026-07-24 20:53" --minutes 3 --out fig.png

# 遠地・弱震は低周波寄り。帯域を下げると拾えることがある
python detectlab.py --at "2026-07-24 20:53" --minutes 10 --band 0.3 1.5 --thr 3 --out fig.png

# イベントID指定 / 手元のキャプチャ・合成CSV
python detectlab.py --event 0001-59462454
python detectlab.py --csv cap.csv --band 1 8 --thr 3

# 取得した生窓をCSVに落として spectrum.py / backtest.py に流す
python detectlab.py --at "2026-07-24 20:53" --dump-csv win.csv --out fig.png
```

### 答え合わせ（緊急地震速報 / 震源との照合）— `--eew`

「その時刻の揺れが本当に地震か」は、**震源からの到達時刻**と**偏光**で検証できる。
`--eew "緯度,経度,深さkm,発生時刻(JST)"` を渡すと、観測点までの震源距離から
**P波・S波の到達予測窓**を全パネルに重ね描きし、その窓の **SNR（背景比）と直線性**を出す。

```bash
# 福島県沖 M3.7 深さ60km 20:52:59発生 との照合
python detectlab.py --at "2026-07-24 20:53" --minutes 10 --band 0.3 1.5 --thr 3 \
    --eew "37.7,141.7,60,2026-07-24 20:52:59" --out fig.png
```

出力例（この事象は距離275kmで弱く、ノイズフロアぎりぎり）:

```
  P窓 20:53:34-20:53:44  SNR=1.09  直線性=0.71  → 微妙(ノイズと分離できず)
  S窓 20:54:00-20:54:17  SNR=1.04  直線性=0.63  → 微妙(ノイズと分離できず)
```

判定は `SNR≥1.5 かつ 直線性≥0.6` で「地震らしい」、`SNR<1.3` で「微妙」。観測点座標は
`--station "lat,lon"` / 環境変数 `NAMZ_STATION_LATLON` / 既定（湯沢町）の順。

### 複数機を重ね描き（`--device` に複数指定 / `--event` に複数指定）

`--device 1 2` のように複数指定すると、デバイスごとに個別読み込み・個別解析した上で
STA/LTA比・直線性の2パネルだけを同一時間軸に重ねて描く（`--at`/`--at-us` 限定）。

```bash
python detectlab.py --at "2026-08-08 03:41:32" --device 1 2 \
    --eew "36.7,140.6,10,2026-08-08 03:41:32" --out overlay.png
```

**`--event` にも複数のevent_idを渡せば同じ重ね描きになる**（device idは各event_idの
先頭4桁から決まるので`--device`は不要、onset時刻の手計算も要らない）。既定では
`events/<id>/` の保存済み範囲をそのまま使う（軽い・保持期限を過ぎていても見られる）。

**何も考えず出せるプレースホルダー**: `<バケット番号>`（event_idの`-`より後ろ、
例 `59577127`）だけ埋めて`--device`に見たい機体を並べれば、`0001-59577127`
のような完全なevent_idを自動で組み立てる（同一地震ならほぼ同じ30秒バケットに
乗るため。バケットが違う機体が混ざる時だけ完全なevent_idを個別に書く）。

```bash
python detectlab.py --event <バケット番号> --device 1 2 --out overlay.png
```

```bash
# 実例
python detectlab.py --event 59577127 --device 1 2 --out overlay.png
```

保存済み範囲より外まで見たい時は `--from-raw` を付ける。各event_idの`onset_us`を
`meta.json`から引き、`raw/`を`--minutes`/`--lead-min`ぶん都度取り直す
（rawの保持期間内でのみ有効。`--event`単体でも使える）。

```bash
python detectlab.py --event 0001-59577127 0002-59577127 --from-raw --minutes 10 --out overlay.png
```

生波形・スペクトログラムは軸の向きが機体ごとに違うため出さない（[device_overlay.md](../docs/device_overlay.md) §2、
方位較正はまだ済んでいない）。STA/LTA・直線性はどちらも**振幅二乗和・共分散固有値という
回転不変量**から出るので、方位較正なしでもそのまま比較できる（同 §3-c の考え方）。
2機が同じタイミングで一致して山を作れば、単独では「微妙」なSNRでも地震由来と判断する
材料になる（実例: [docs/log/2026-08-08-ibaraki-m3.8-post-hoc-detection.md](../docs/log/2026-08-08-ibaraki-m3.8-post-hoc-detection.md)）。

**ちょうど2機の重ね描きなら、直線性の一致度パネル（3段目）が自動で付く。** 2機の直線性を
共通の時間軸へ線形補間で揃え、窓 `--corr-win`（既定2秒）の移動Pearson相関を描く。
環境ノイズは機体間で無相関（相関係数が-1〜1で激しく上下）なのに対し、本物の地震動は
両機に同時に乗るため相関が1に近づいて張り付く。STA/LTAの山が収まった後も、コーダ
（後続波・表面波）が続く間は相関が高いまま残ることがあり、「閾値を跨いだ短い区間」より
実際に揺れていた時間の方が長いと分かることがある（実例:
[docs/log/2026-08-23-ibaraki-nanbu-m5.9-post-hoc-detection.md](../docs/log/2026-08-23-ibaraki-nanbu-m5.9-post-hoc-detection.md)）。
3機以上の重ね描きでは「どの組を見せるか」が自明でないため、このパネルは付かない。

`--dump-csv` は指定すると各デバイスに `.dev<id>` を挟んだファイル名で個別保存する。

### 主なオプション

| オプション | 既定 | 意味 |
|-----------|------|------|
| `--at` / `--at-us` / `--event` / `--csv` | （必須・排他） | データ源。時刻中心窓 / epoch µs / イベントID(複数可・裸のバケット番号可) / CSV |
| `--device ID [ID ...]` | `1` | デバイスID（`--at`系で必須）。`--event`では裸のバケット番号の展開に使う。2つ以上で重ね描きモード |
| `--from-raw` | 無効 | `--event`指定時、`events/`の保存済み範囲ではなく`raw/`を`--minutes`/`--lead-min`ぶん都度取り直す |
| `--minutes N` | `3` | `--at` 系の窓長[分]。中心の前後 N/2 分 |
| `--band LO HI` | `1 10` | バンドパス帯域[Hz]。遠地・弱震は `0.3 1.5` 等に下げる |
| `--sta` / `--lta` | `1` / `30` | STA/LTA の短期/長期窓[秒] |
| `--thr` | `4` | STA/LTA の onset 検出閾値 |
| `--axes` | `xyz` | 解析に使う軸。`xy`=水平のみ（z軸の低周波ノイズが大きい時、遠地弱震で有利） |
| `--rect-win` | `3` | 直線性の移動窓[秒] |
| `--corr-win` | `2` | 2機重ね描き時の直線性一致度パネルに使う移動相関の窓[秒] |
| `--eew "lat,lon,depth,時刻"` | なし | 震源との照合。P/S到達窓＋SNR/直線性 |
| `--station "lat,lon"` | 湯沢町 | 観測点座標（`--eew` 用） |
| `--dump-csv PATH` | なし | 取得した生窓を `t_us,x,y,z` CSVで保存 |
| `--bucket` | env/terraform | rawバケット。既定は `NAMZ_RAW_BUCKET` → `terraform output -raw data_bucket` |
| `--out PATH` / `--show` | 画面表示 | PNG保存 / `--out` 時も画面表示 |

> 注: 遠地・弱震は帯域選びで感度が変わる（遠いほど低周波寄り＝ノイズ帯と重なる）。
> `--band` を振って STA/LTA ピークが立つ帯域を探すのが実践的。
>
> `--axes xy`（水平のみ）: IIS3DHHC は z軸(垂直)の低周波ノイズが大きいので、遠地弱震では
> z を捨てて水平2軸で組むと背景が下がり感度が上がることがある。実際 2026-07-28 の熊本
> (震央距離約870km)は 3軸では埋没したが、`--axes xy --band 0.5 2` で P波到達時刻に
> STA/LTA が立った。表面波は水平成分に乗りやすいのも追い風。

### tenki.jp のURLから一発で（`tenki_view.py`）

`detectlab.py` に諸元（緯度経度・深さ・発生時刻）を手入力する代わりに、tenki.jp の
地震詳細URLを渡すだけで済むラッパ。ページから諸元を抽出し、`--at` と `--eew` を
組み立てて `detectlab.py` を呼ぶ。震源距離から既定バンドも自動選択する。

```bash
python tenki_view.py "https://earthquake.tenki.jp/bousai/earthquake/detail/2026/07/24/2026-07-24-20-53-08.html" \
    --minutes 8 --out fig.png
# → # 福島県沖  M4  深さ50km  発生 2026-07-24 20:53:00 (分単位)
#   # 最大震度1  震央距離268km 震源距離273km
#   （detectlab がP/S到達窓つきの図を生成）

python tenki_view.py <URL> --dry-run   # 実行せず組み立てたコマンドだけ表示
```

`--band`/`--thr`/`--out`/`--bucket` などの追加オプションはそのまま `detectlab.py` に渡る
（`--band` 未指定なら距離から自動: >700km→`0.3 1.5` / >300km→`0.5 3` / それ以下→`1 10`）。

制約: tenki の発生時刻は**分単位**（秒なし）なので到達窓に±30秒程度の不定性が乗る。
確定前の速報ページは緯度経度が「---」で取れないことがあり、その時は確定を待つか
`detectlab.py` に手で `--eew` を渡す。HTML取得は標準ライブラリ（追加依存なし）。

## S3から読む時は常にs3cache（`tools/s3cache.py`）

**tools/配下でS3から読む（`list_objects_v2`/`get_object`）コードは、生の
`boto3.client("s3")`を自作せず常に`tools/s3cache.py`を使うこと。** raw batch・event
batchは書き込み後不変なので、1回しか使わないつもりの解析でもキャッシュして損は無い
（都度スクラッチで同じラッパーを書き直していたのを、`detectlab.py`組み込みを機に
1本化した）。

```python
import s3cache
s3 = s3cache.cached_client()  # store.load_window / load_event にそのまま渡せる
```

- **書き込み(`put_object`/`copy_object`)には使えない**。`CachedS3`は読み取り2メソッド
  (`list_objects_v2`/`get_object`)しか実装していない。`promote_event.py`のように
  S3へ書くツールは、書き込み用に生の`boto3.client("s3")`をそのまま使うこと（読み取り
  箇所だけs3cacheに差し替えるのは構わない）。
- **object keyをそのままローカルパスにミラーする**（`.s3cache/raw/.../<device>-<startus>.bin`
  のように、S3のKeyをそのまま`.s3cache/`の下にぶら下げる）。`start_us`/`end_us` で丸ごと切った窓単位で
  キャッシュすると、窓をわずかにずらしただけで丸ごと引き直しになる。バッチ(30秒粒度)単位で
  キャッシュすれば、窓が重なっている限り差分だけ取得すれば済む。
- キャッシュするのは `get_object` だけ（`list_objects_v2` は毎回本物のS3へ通す。新着を
  見逃さないためコストもほぼ無い）。
- **raw/とevents/はキー末尾`<batch_start_us:020d>.bin`が一致すれば中身も同一バイト列**
  （`events/`は検知時に`copy_object`で`raw/`をそのままコピーしたもの）。片方が未キャッシュ
  でももう片方が既にキャッシュ済みならそちらを流用してS3を叩かない。rawを読んだ後に
  そのイベントだけ見たい／eventを読んだ後に前後のrawが見たい、を行き来してもレイテンシが
  乗らない。
- worktreeで作業していても `.s3cache/` は**メインチェックアウト側の絶対パス**を指す
  （`git rev-parse --git-common-dir` の親を使う。worktreeごとに毎回別ディレクトリだと
  キャッシュが効かない）。
- `detectlab.py` は既定でこれを使う（`--no-cache`で生のboto3に戻せる）。

## テスト

```bash
pytest tests/ -q
```

検証内容: フィルタの各周波数応答、丸め規則、震度階級境界、
静置ノイズが有感未満になること、振幅10倍で raw震度が +2.0 になること（式の正しさ）、
FIR版のフィルタ後波形が FFT版とピーク相対誤差15%未満で一致すること。
