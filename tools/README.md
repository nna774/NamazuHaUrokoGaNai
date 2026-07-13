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
python flag_event.py list                        # 立っているものを一覧
```

`mark`/`unmark` は対象を一覧表示して確認を取ってから実行する（`--before` は複数件を
一気に書き換えるため特に注意）。確認を省くときは `-y`/`--yes`。

`flag_event.py` は AWS 認証情報（通常の boto3 の解決）で DynamoDB を直接更新する。
フラグを立てたイベントはダッシュボードの一覧では隠れ（「全件」表示でのみ薄く出る）、
詳細で「人工地震（テスト等）」と表示される。震度や確定状態は変えない。

## テスト

```bash
pytest tests/ -q
```

検証内容: フィルタの各周波数応答、丸め規則、震度階級境界、
静置ノイズが有感未満になること、振幅10倍で raw震度が +2.0 になること（式の正しさ）、
FIR版のフィルタ後波形が FFT版とピーク相対誤差15%未満で一致すること。
