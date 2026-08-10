# Shindoの内部バッファをint16固定小数点化し、静的RAMを約15KB削減した

## 経緯

`memo.md`にユーザーが貼った「型の格下げによる半減」のアイデア（震度計算の内部配列を
`float`から`int16_t`へ落とす）が実際に意味があるか相談を受けた。DRAM予算が
`TlsMemPool`導入や`Batch`プール化の攻防で数百バイト単位まで削られてきた経緯
（[2026-08-10-tls-dedicated-pool.md](2026-08-10-tls-dedicated-pool.md)ほか）を踏まえると、
`firmware/lib/Shindo`の`composite_[6000]`(float, 24000B)と`hist_[3][511]`(float, 6132B)を
合わせた約15KBは削減余地として大きいと判断し、実装した。

## 実装

`Shindo.h`/`Shindo.cpp`（`firmware/lib/Shindo/`）:

- `hist_[3][kJmaFirNumTaps]`（FIRフィルタの循環履歴）を`int16_t`化。スケール
  `kGalScale=10`（1LSB=0.1gal）、表現域±3276.7galはIIS3DHHC(±2452gal)・
  ADXL355(±2008gal)いずれのフルスケール（重力込み）も余裕を持って収まる。
  畳み込みはスケール倍されたまま積算し、最後に1回だけ割って戻す。
- `composite_[kWindowSamples]`（フィルタ後合成加速度の60秒移動窓）も`int16_t`化。
  ただしスケールは`hist_`と分け、`kCompositeScale=28`（1LSB≈0.036gal、表現域
  ±1170gal≈JMA計測震度7超）とした。理由は次節。

`sizeof(Shindo)`は15104B（旧30160B相当から半減）。実機ビルドの`RAM:`表示は
esp32dev/adxl355とも**78180B→63116Bへ15064B減**（`pio run`実測）。

## composite_のスケールをhist_と分けた理由（ホストg++照合で発見）

`tools/backtest.py`と同じ考え方で、ホストg++に元の`float`実装（`ShindoFloat`と
改名した写し）と新実装を並べてコンパイルし、同一の加速度ストリームを両方に
`push()`して`currentIntensity()`の差を突き合わせた（コミットはしていない一時
ハーネス、`$CLAUDE_JOB_DIR/tmp/shindo_verify/`で作業）。

- `hist_`だけint16化（`composite_`はfloatのまま）: 実データ4本（静止2本・揺れ・
  タップ）＋合成地震(5〜1200gal)＋境界を狙った弱地震(3〜15gal、複数seed)の
  全ケースで、`kAlertIntensity`(0.5)を跨ぐ判定が完全一致。挙動変化なし。
- `composite_`もint16化（`kGalScale=10`と共用のまま）: 弱い揺れ（震度0.5前後で
  推移する合成地震）で、0.25秒刻みの閾値判定が360回中最大7回ズレるケースが
  見つかった。原因は`composite_`自体の保存時丸め（0.1gal刻み）——`hist_`経由の
  誤差はcomposite値そのものに対しrms 0.007gal程度と小さく、支配的だったのは
  `composite_`の保存丸めだった。
- スケールを10〜32の範囲で振って再テストしたが、**分解能を上げてもズレの発生箇所が
  移動するだけで消えない**（量子化と閾値判定の宿命的な境界ジッタ）。表現域との
  兼ね合いで`kCompositeScale=28`（震度7超をカバー）を採用し、`hist_`とは別の
  定数に分離した。

## この程度のジッタを許容した判断

- 閾値0.5はJMA震度スケールの「震度0→1」境界（人が気付くかどうかの瀬戸際）で、
  定常時のベースライン（[noise.md](../noise.md)、-1.2〜-0.55）からは十分離れている。
  ノイズに埋もれているわけではないが、震度1未満のごく軽微な揺れでしか起きない。
- ファーム側の`holdSeconds`は連続2秒必要で単発のズレはリセット側に働くだけなので、
  本震のような明確な閾値超過では影響しない。
- 仮にデバイス速報（`device_prompt`）が遅れる/落ちても、`lambda/detect/handler.py`の
  `THRESHOLD=0.5`・`HOLD_SECONDS=2.0`が生の加速度データから独立に毎バッチFFT評価
  しており、2秒以上の実揺れなら`cloud_confirmed`イベントとして必ず記録される
  （Slack通知の下限`NOTIFY_CONFIRM_MIN=1.5`はイベント記録ではなく通知だけを絞る）。
  デバイス側の判定はクラウド側の二重チェックがあるので、多少のジッタは許容範囲。

## 検証

- ホストg++での`ShindoFloat`（旧実装の写し）対`Shindo`（新実装）突き合わせ
  （実データ4本＋合成波形多数、一時ハーネスは未コミット）
- `pio run -e esp32dev -e adxl355`成功、RAM使用量15064B減を確認
- `firmware/test/run.sh`（Batch/NamzWire/TlsMemPoolCoreのホストテスト）通過
  （Shindo自体はここに恒常テストとして組み込んではいない）

実機投入はまだ。
