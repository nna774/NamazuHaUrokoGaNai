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
**バンドパス波形・スペクトログラム（時間×周波数）・STA/LTA比**の3視点で可視化し、
立ち上がり候補時刻を出力する解析ビュー。STA/LTA（短期/長期エネルギー比）は地震観測網の
トリガと同じ原理で、振幅がノイズに紛れても帯域集中した過渡だけがピークする。

```bash
# ある時刻を中心に前後N分をS3(raw/)から取って解析（--at はJST）
python detectlab.py --at "2026-07-24 20:53" --minutes 3 --out /tmp/2053.png
# イベントID指定（events/<id>/ を連結）
python detectlab.py --event 0001-59462454
# 手元のキャプチャ/合成CSVで
python detectlab.py --csv cap.csv --band 1 8 --thr 3
# 取得した生窓をCSVに落として spectrum.py / backtest.py に流す
python detectlab.py --at "2026-07-24 20:53" --dump-csv /tmp/2053.csv --out /tmp/2053.png
```

主なオプション: `--band LO HI`（帯域[Hz]、既定 `1 10`）、`--sta`/`--lta`（STA/LTA窓[秒]、
既定 `1`/`30`）、`--thr`（検出閾値、既定 `4`）。データはAPIではなく `lambda/common` 経由で
S3を直読みする（APIは30秒超でエンベロープに間引かれ、スペクトル解析に使えないため）。
rawバケットは `--bucket` / 環境変数 `NAMZ_RAW_BUCKET` / `terraform output -raw data_bucket`
の順で解決。遠地・弱震は帯域選びで感度が変わる（遠いほど低周波寄り＝ノイズ帯と重なる）ので
`--band` で追い込む。本CLIは検出**器**ではなく解析**ビュー**（自動検知は detect Lambda の担当）。

## テスト

```bash
pytest tests/ -q
```

検証内容: フィルタの各周波数応答、丸め規則、震度階級境界、
静置ノイズが有感未満になること、振幅10倍で raw震度が +2.0 になること（式の正しさ）、
FIR版のフィルタ後波形が FFT版とピーク相対誤差15%未満で一致すること。
