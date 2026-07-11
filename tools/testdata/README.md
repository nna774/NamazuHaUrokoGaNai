# testdata — 実機キャプチャ

| ファイル | 内容 |
|----------|------|
| `sample_rest.csv` | IIS3DHHC + ESP32(TTGO T-Display系)で静置60秒。10xオーバーサンプル。計測震度 **-0.6(震度0)** のノイズフロア基準データ |

用途: 解析ツールやアルゴリズム変更時のリグレッション確認。

```bash
python backtest.py testdata/sample_rest.csv   # I が -0.6 付近なら健全
python spectrum.py testdata/sample_rest.csv
```
