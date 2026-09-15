# 地震候補スキャン(docs/auto_judge.md)を実装した

設計（[log/2026-09-08-auto-judge-narrowed-to-scan-notify.md](2026-09-08-auto-judge-narrowed-to-scan-notify.md)）
が固まったのを受けて、PR #212をマージし新ブランチでコードを実装した。

## 実装した内容

- **新規Lambda `lambda/quake_scan/handler.py`**: 日次でJMAの`list.json`を取得し、
  「投げる価値あり」「近すぎ」は全件・「遠すぎ」はM≥4.0だけを候補にし、まだ通知して
  いない候補を1日1通のSlackダイジェストで通知する。毎週土曜には閾値見直しの一言を
  追記する。解析・判定・保存はしない。
- **`lambda/common/quake_scan.py`**: 状態管理。通知済みJMA `eid`の集合（TTL 60日）と
  最終成功実行時刻(`last_success_at_us`)をDynamoDB(`namazu-quake-scan`)に持つ。
  `ota_watch.py`と同じ「純粋関数(判定)＋薄いDynamoDBアクセス」の分離。
- **`watchdog/handler.py`に停滞検知の1ブロック追加**: デバイスループの外で
  `quake_scan.evaluate_stuck()`を1回だけ呼ぶ。32時間動いていなければ通知。
- **`tools/detection_range.py`に`FAR_BUT_NOTABLE_MAG = 4.0`と`worth_notifying()`を追加**。
  閾値を1箇所に集約し、`scan_quakes.py`とLambdaの両方が同じ関数を呼ぶ。
- **`tools/scan_quakes.py`の候補整形を`format_candidate()`に切り出し**、CLI出力と
  Lambda通知で共用（`detectlab.py`コマンド雛形込みの同じ整形）。
- **terraform**: `namazu-quake-scan`テーブル新設、`quake_scan` Lambda + EventBridge
  日次ルール、IAMに`BatchGetItem`/`BatchWriteItem`追加、`build_lambda.sh`に
  `quake_scan`用のビルドを追加。

## 想定外だった作業: station.pyへの切り出し

`lambda/quake_scan`が候補抽出に使う`scan_quakes.py`・`detection_range.py`は、
震源ジオメトリの計算(`hypocentral_km`等)を`detectlab.py`からimportしていた。
`detectlab.py`はモジュールレベルで`scipy`をimportしており、そのままLambdaに
同梱すると解析用の重い依存(scipy)を候補抽出だけのジョブに持ち込むことになる。

`hypocentral_km`/`bearing_deg`/`parse_station`/`DEFAULT_STATION`は`math`/`os`しか
使わない純粋関数だったので、`tools/station.py`（新規、依存なし）に切り出し、
`detectlab.py`・`detection_range.py`・`scan_quakes.py`・`detection_map_svg.py`を
そちらからimportするよう直した。`detectlab.py`は`from station import ...`で
再輸出する形になり、既存の`detectlab.hypocentral_km(...)`のような呼び出し方は
互換のまま動く（テストで確認済み）。結果、`lambda/quake_scan`はnumpyだけで
scipyを持ち込まずに済んでいる。

## 確認したこと

- `pytest lambda/tests/ tools/tests/`: 268件全通過（新規テスト12件を含む:
  `worth_notifying`の判定・`quake_scan`の重複排除/停滞判定の純粋関数・
  handlerの配線をモックで通す統合テスト）。
- `terraform validate`・`terraform plan`（`namazu-admin`プロファイル）で
  構文・依存関係を確認。`build_lambda.sh`で`quake_scan.zip`を実際にビルドし、
  中身にscipyが含まれず(`numpy.libs/`のOpenBLASは別物)、`detection_events.csv`・
  `jismo/`・`scan_quakes.py`等が正しく同梱されていることを確認した。
- `terraform plan`は「5 to add, 5 to change, 0 to destroy」——新規リソース
  （テーブル・関数・EventBridgeルール・ターゲット・パーミッション）5個と、
  既存Lambda4関数への環境変数追加+watchdogの差し替えのみで、破壊的な変更は無い。

## まだやっていないこと

**`terraform apply`は実行していない。** 実際にAWSへデプロイし、EventBridgeの
初回実行を見届けるところからが次のステップ。デプロイ後は最低でも1〜2週間、
できれば1ヶ月程度実データを回してから、`docs/auto_judge.md`に明記した通り
M≥4.0・窓28時間・失敗検知32時間の各閾値を実例で検証すること。
