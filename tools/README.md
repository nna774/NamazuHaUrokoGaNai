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

# 実機シリアルをCSVに保存（LSB->gal換算）
python capture_serial.py --port /dev/tty.usbserial-XXXX --seconds 60 > cap.csv
python backtest.py cap.csv --trace

# ファーム用のFIR係数ヘッダを生成
python gen_fir_header.py   # -> firmware/lib/Shindo/JmaFirTaps.h

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

`flag_event.py` は AWS 認証情報（通常の boto3 の解決）で DynamoDB を直接更新する。
フラグを立てたイベントはダッシュボードの一覧では隠れ（「全件」表示でのみ薄く出る）、
詳細で「人工地震（テスト等）」と表示される。震度や確定状態は変えない。

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

### 主なオプション

| オプション | 既定 | 意味 |
|-----------|------|------|
| `--at` / `--at-us` / `--event` / `--csv` | （必須・排他） | データ源。時刻中心窓 / epoch µs / イベントID / CSV |
| `--minutes N` | `3` | `--at` 系の窓長[分]。中心の前後 N/2 分 |
| `--band LO HI` | `1 10` | バンドパス帯域[Hz]。遠地・弱震は `0.3 1.5` 等に下げる |
| `--sta` / `--lta` | `1` / `30` | STA/LTA の短期/長期窓[秒] |
| `--thr` | `4` | STA/LTA の onset 検出閾値 |
| `--rect-win` | `3` | 3軸直線性の移動窓[秒] |
| `--eew "lat,lon,depth,時刻"` | なし | 震源との照合。P/S到達窓＋SNR/直線性 |
| `--station "lat,lon"` | 湯沢町 | 観測点座標（`--eew` 用） |
| `--dump-csv PATH` | なし | 取得した生窓を `t_us,x,y,z` CSVで保存 |
| `--bucket` | env/terraform | rawバケット。既定は `NAMZ_RAW_BUCKET` → `terraform output -raw data_bucket` |
| `--out PATH` / `--show` | 画面表示 | PNG保存 / `--out` 時も画面表示 |

> 注: 遠地・弱震は帯域選びで感度が変わる（遠いほど低周波寄り＝ノイズ帯と重なる）。
> `--band` を振って STA/LTA ピークが立つ帯域を探すのが実践的。

## テスト

```bash
pytest tests/ -q
```

検証内容: フィルタの各周波数応答、丸め規則、震度階級境界、
静置ノイズが有感未満になること、振幅10倍で raw震度が +2.0 になること（式の正しさ）、
FIR版のフィルタ後波形が FFT版とピーク相対誤差15%未満で一致すること。
