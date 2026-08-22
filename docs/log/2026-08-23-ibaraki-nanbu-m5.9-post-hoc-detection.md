# 2026-08-23 茨城県南部M5.9、速報→クラウド確定まで自動で完走。detectlabで裏取り

気象庁発表（震源N36.0/E140.1・深さ70km・02:00:50発生、M5.9、最大震度5弱〈茨城県北部・
南部/埼玉県南部/千葉県北西部/東京都23区〉）を受けて確認した。

## 自動検知は正常に完走していた

`/events?all=1` に該当イベントがあり、**速報・確定報とも両機で自動発報済み**:

| | device1 | device2 |
|---|---|---|
| event_id | `0001-59580602` | `0002-59580602` |
| onset | 02:01:04.95 | 02:01:04.81 |
| device_prompt / cloud_confirmed | true / **true** | true / **true** |
| max_intensity (confirmed) | 2.7 | 2.6 |
| peak_gal | 8.77 | 8.50 |

八丈島東方沖M5.5（[docs/log/2026-08-21](2026-08-21-hachijo-oki-m5.5-post-hoc-detection.md)）と違い
`HOLD_SECONDS`（現在0.3秒）を越える持続があったため、確定報・Slack通知まで手を加えずに
自動で完走している。今回はイベントとしては「取れている」ことが分かっている状態からの
事後解析依頼だったので、以下は答え合わせ。

## detectlab事後解析

```bash
python tools/detectlab.py --at "2026-08-23 02:00:50" \
  --eew "36.0,140.1,70,2026-08-23 02:00:50" --minutes 8 --device 1 2 3 \
  --out docs/log/img/2026-08-23-ibaraki-nanbu-m5.9-3axis.png
```

震央距離155km・震源距離170km。標準設定（3軸・1-10Hz）で両機とも極めて明瞭:

| | device1 (IIS3DHHC) | device2 (ADXL355) | device3 (ピエゾ) |
|---|---|---|---|
| STA/LTA peak | 21.44 | 24.37 | 13.57（直線性nan、参考外） |
| P窓(02:01:11-18) SNR/直線性 | 16.11 / 0.68 → 地震らしい | 22.42 / 0.69 → 地震らしい | 1.34 / nan → 要検討 |
| S窓(02:01:27-38) SNR/直線性 | 46.26 / 0.87 → 地震らしい | 63.29 / 0.85 → 地震らしい | 1.38 / nan → 要検討 |

過去の確定事例（八丈島東方沖M5.5: STA/LTA peak 6.20/6.47）より1桁近く高い値で、
自動確定の`I=2.7/2.6`という高めの値と整合する。device3（ピエゾ）はこの規模でも
イベント自体が生成されず、P/S窓とも直線性nan・SNR~1.3でノイズと未分離
（既知のノイズフロア問題、`docs/piezo.md`参照。実験機のため判定対象外）。

![3軸1-10Hz重ね描き](img/2026-08-23-ibaraki-nanbu-m5.9-3axis.png)

## 結論・処理

- 速報・確定報・detectlab事後解析・気象庁発表の四者が一致。実際の地震であることに
  疑いはない。`tools/flag_event.py note`で両イベントに解析結果を記録し、
  `relate 0001-59580602 0002-59580602`で相互リンクした
  （運用方針は[docs/log/2026-08-20](2026-08-20-relate-events-across-devices.md)）。
- このレポのworktree（`.venv`が無い）から作業したため、`tools/detectlab.py`の
  rawバケット自動解決（`terraform output`）が失敗した。共有チェックアウト
  （`/Users/nana/codes/NamazuHaUrokoGaNai/terraform`）側で`terraform output -raw data_bucket`
  を引いて`--bucket`に明示指定・`.venv/bin/python3`をフルパスで呼ぶことで回避した。
  worktreeで事後解析系ツールを使う時は毎回このひと手間が要る。
