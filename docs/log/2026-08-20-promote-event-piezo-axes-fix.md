# 2026-08-20 `promote_event.py`がピエゾ機(非校正・1軸)を昇格できないバグを直した

2026-08-20 14:28茨城県沖M3.5の手動イベント化（[log/2026-08-20-ibaraki-oki-m3.5-post-hoc-detection.md](2026-08-20-ibaraki-oki-m3.5-post-hoc-detection.md)）で
device1/2は成功したが、device3（ピエゾ実験機）で`IndexError: index 1 is out of bounds
for axis 1 with size 1`が発生した。

## 原因

`tools/promote_event.py`の計測震度計算が`gal[:, 0], gal[:, 1], gal[:, 2]`と3軸決め打ちで、
axes可変（ピエゾは1軸）を考慮していなかった。`lambda/detect/handler.py`は
`wire.is_calibrated(sensor_type)`で非校正センサをそもそも震度計算に掛けない
ガードを持っているが、`promote_event.py`には同等のガードが無かった。

## 直したこと

`gal.shape[1] >= 3`で分岐し、3軸未満（非校正センサ）なら計測震度計算をスキップして
`intensity=0.0, a0=0.0`・`peak_gal`は生値の絶対値最大とし、波形の永久保存だけ行うように
した。CLAUDE.mdの「物理量前提のロジックだけをdevice_id単位で迂回させる」方針
（`api`の`_pad_to_3ch`と同じ発想）を`promote_event.py`にも適用した形。

`tools/tests/test_promote_event.py`の既存テスト（S3/DynamoDBを叩かないヘルパー関数の
単体テストのみ）はそのまま通過。`main()`本体はモック無しでは検証できない構造のため、
実機データでの動作確認（device3のdry-run/実行）で代えた。

```
$ python tools/promote_event.py --onset "2026-08-20 14:29:40" --pre 60 --post 120 \
    --device 3 --dry-run
# 非校正センサ(axes=1)のため計測震度は計算不可。peak(raw)=320.677  波形のみ保存する
```
