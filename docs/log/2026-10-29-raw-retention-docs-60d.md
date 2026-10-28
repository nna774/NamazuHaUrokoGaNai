# 2026-10-29 rawの保持日数の記述を60日に揃えた

2026-08-11に`raw_retention_days`を90→60日に短縮した
（[log](2026-08-11-events-accidental-deletion-protection.md)、`acb2118`）が、そのとき`docs/design.md`しか
直しておらず、他の「現状」を述べる記述に「90日」が残っていた。方位推定の試作
（[log](2026-10-29-azimuth-from-epicenter-trial.md)）で8/22・8/21のrawを引こうとして空だったことから発覚した
（実際の`aws s3api get-bucket-lifecycle-configuration`は`raw/`が60日expire）。

直したのは現状を述べる箇所だけ: `README.md`・`terraform/README.md`・`tools/README.md`・
`tools/promote_event.py`（docstringとエラーメッセージ）・`docs/post_hoc_detection.md`・
`lambda/common/event_backfill.py`のコメント。

直していないもの:
- `docs/log/`の過去ログと`docs/progress.md`の過去行: 当時の記述で、履歴として残す。
- `plan.md`: 最初の実装計画（当時の決定）。
- `lambda/common/device_temp.py`の`TTL_DAYS=90`: 温度テーブルのTTLという別の値で、rawの保持とは独立。

なお、アプリから見える寿命は60日だが、versioningのnoncurrent versionは30日余分に残る
（60+30=90日。バージョン指定でのみ復旧可能）。通常のGETは60日で404になる。
