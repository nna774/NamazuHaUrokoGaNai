# testdata — 実機キャプチャ

IIS3DHHC + ESP32(TTGO T-Display系) 実機。10xオーバーサンプル・100Hz。

| ファイル | 内容 | FFT計測震度 | リアルタイム震度(速報) |
|----------|------|:---:|:---:|
| `sample_rest.csv`  | 静置60秒（ノイズフロア） | -0.6（震度0） | 0.0 |
| `sample_tap.csv`   | 机を数回叩く（単発＝生活振動） | 2.0 | 0.7（アラート未満で弾く） |
| `sample_shake.csv` | 連続で揺らす（地震相当） | 3.4 | 3.3（検知・両者一致） |

測定系の検証を示す3点セット。単発は弾き、連続揺れは速報と確定が一致する。

用途: 解析ツールやアルゴリズム変更時のリグレッション確認。

```bash
python backtest.py testdata/sample_rest.csv    # -0.6 付近
python backtest.py testdata/sample_shake.csv   # 3.4 付近、FIRとの差 < 0.3
python spectrum.py testdata/sample_rest.csv
```
