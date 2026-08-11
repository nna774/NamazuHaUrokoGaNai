# ピエゾ実験機、phase1（クラウド統合）の設計方針を決めた

[docs/piezo.md](../piezo.md)でphase0（ローカルSerial出力のみ）を達成した後、
[docs/other-sensors.md §2](../other-sensors.md#2-アーキテクチャ上の要点-配送と物理量前提ロジックを分けて考える)
で「未定」としていたphase1の設計を、実装前に詰めた。コード変更はまだ無い（設計のみ）。

## 1. 物理量前提ロジックの迂回判定は、DynamoDBを引く必要が無いと判明

`other-sensors.md`は「都度DynamoDBを引くか、device_idの値そのもの（ID帯）で
静的判定するか」を未定としていたが、既存コードを読んだところ**どちらも不要**と
分かった。`lambda/ingest/handler.py`が既に毎バッチ
`device_meta.record_sensor_type(device_id, sensor_type)`を呼んでおり、
`namazu-devices`には`sensor_type`が自動記録済み。一方
**detect Lambda(`lambda/detect/handler.py`)にはsensor_typeを見た分岐が
そもそも1つも無い**（IIS3DHHC/ADXL355の2種類しかなく、両方ともgal校正済み
だったため要らなかっただけ）。

detect Lambdaはバッチをパースした時点で`BatchMeta.sensor_type`を既に手元に
持っている。したがって**DynamoDB参照は不要で、`_process()`冒頭に
sensor_typeガードを1行足すだけで震度計算を丸ごとスキップできる**。

## 2. `device_prompt`自動生成は、コード変更なしで安全

`lambda/ingest/handler.py`の`_handle_alert()`は、ファーム自身が計算して送る
アラートJSON（`realtime_intensity`/`peak_gal`）を無条件に受けてイベント化する。
アラートJSON自体に`sensor_type`は乗らない。**ピエゾ側ファームがこのアラートAPIを
叩く実装をしなければ、この経路は自然に発火しない。**`other-sensors.md §5`の
「このセンサ単独でのイベント自動生成はしない」は、ファームに機能を実装しない
という不作為だけで担保できる。

## 3. `SENSOR_TYPE_PIEZO = 128`、番号帯を分ける

`docs/design.md`で`config.h`の`SensorType`enumが`kSensorAdxl355=1`・
`kSensorLsm6dso=2`を予約済みと判明（BMI160も候補にある）。つまり`0,1,2,...`は
「加速度センサチップ」の列としてまだ埋まりかけている。ここに加速度センサですら
無いピエゾを次の空き番号(3)で割り込ませるのは分類として筋が悪いと判断し、
`wire.py`の`sensor_type`(u8)に帯域を切ることにした:

- `0〜127`: 加速度センサチップ（gal校正対象。既存2種+予約2種）
- `128〜249`: 加速度ではない・非校正の生値センサ
- `250〜254`: 予約（未使用のまま空けておく）
- `255`: `FAKE`（結合試験用、既存）

ピエゾは`SENSOR_TYPE_PIEZO = 128`。表示名（`SENSOR_TYPE_NAMES`、ダッシュボード
デバイス詳細ページで使う）は具体的なセンサ名を出したいので、`RAW`のような抽象名
ではなく個別に採番する方針にした（gal校正済みかどうかの判定は表示名と別に
allowlistで持てば困らない）。

**`255`(`FAKE`)は迂回対象に含めない。**`firmware/lib/FakeSensor/FakeSensor.h`は
IIS3DHHCと同じ換算(0.076mg/LSB)でgal相当の値を実際に送る結合試験用センサで、
震度計算パイプライン自体をend-to-endで試す用途（静穏なノイズしか出さないため
閾値には掛からないだけで、gal計算自体は通す設計）。detect Lambdaのガードは
「`sensor_type >= 128`」ではなく「`128〜249`の範囲」で判定する必要がある。

## 4. ワイヤ形式は`axes: 1`で正直に送り、dashboard対応はapi Lambda 1箇所に閉じる

当初「3軸のままx軸だけ使いy,z=0埋めで送る」案（`dashboard/app.js`が随所で
`wf.x`/`wf.y`/`wf.z`を決め打ちしているため無改修で済む）で妥協しかけたが、
`lambda/api/handler.py:361 _waveform_payload()`が波形JSONを組み立てる**唯一の
関数**で、dashboardはS3の生バイナリを直接読まずここが返すJSONしか見ていないと
確認できた。したがって:

- `lambda/common/wire.py`の`parse()`は`axes != 3`ガードを外し、`axes`を使った
  `reshape(count, axes)`に直す（ワイヤ形式・ファーム実装は`axes=1`で正直に送る）
- `_waveform_payload()`（と`envelope`モードの`reshape(-1, bucket, 3)`側）の手前で、
  `gal`の列数が3未満ならy,z列を0埋めして3列に揃えるpadding処理を1箇所挟む
- `dashboard/app.js`は無改修で済む

「app.jsが2000行を超えたら軸を可変対応にリファクタする」という将来課題を
先送りする形（B案）よりも、ワイヤ形式を嘘の3軸に見せかけずに済むこちらの形の方が
筋が良いと判断した。

## 5. firmwareの配置は本線`firmware/`へ統合

`docs/piezo_phase0/`は独立PlatformIOプロジェクトのまま育てず、本線`firmware/`
配下の`[env:]`として統合する方針にした。`tools/provision_device.py`の
NVSプロビジョニング配線（`secrets_provision.h`生成、`SENSOR_ENV`）をそのまま
再利用できる。

## 次に可能になったこと

phase1着手に必要な設計判断が出揃った。実装順序:

1. `wire.py`に`SENSOR_TYPE_PIEZO=128`と帯域コメントを追加、`axes`可変対応
2. `lambda/detect/handler.py`の`_process()`にsensor_typeガード（`128〜249`の
   範囲のみスキップ、`255`は除く）を追加
3. `lambda/api/handler.py`の`_waveform_payload()`にpadding処理を追加
4. `tools/provision_device.py`の`SENSOR_ENV`にpiezo用env追加
5. `firmware/`にpiezo用`[env:]`とセンサ読み取りコードを追加（batch-uplink組み込み）
6. `tools/devices.json`へのdevice_id払い出し → サーバ側apply → 焼く
7. 実機送信確認、S3格納・dashboard波形表示の確認
