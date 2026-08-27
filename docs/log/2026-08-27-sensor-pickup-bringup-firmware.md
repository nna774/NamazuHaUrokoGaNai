# 2026-08-27 質量-バネ系ピックアップ候補センサの机上確認用ブリングアップファーム

## 何をしたか

[docs/other-sensors.md §3.1/3.2](../other-sensors.md#31-光学式候補の発展形-質量-バネ系連続出力ピックアップ雑談ベース未着手)
で候補に挙げていた4部品(SS49E・MLX90393・PMW3901・PMW3360DM)が実機到着したのを受け、
phase0の「机上確認」用ブリングアップファームを4本書いた。

- `firmware/src/hall_main.cpp` — SS49E、analogRead
- `firmware/src/mlx90393_main.cpp` — MLX90393、I2C（`tedyapo/arduino-MLX90393`）
- `firmware/src/pmw3901_main.cpp` — PMW3901、SPI（`bitcraze/Bitcraze_PMW3901` タグ1.2）
- `firmware/src/pmw3360_main.cpp` — PMW3360DM、SPI（`SunjunKim/PMW3360` タグ1.1.0）

4本ともWiFi/送信/NVSは使わず、Serialへ生値をCSVで吐くだけ。`main.cpp`とはsetup()/loop()
排他なので、`platformio.ini`に`[env:hall-bringup]`等の専用envを4つ追加し、
`[env:esp32dev]`の`build_src_filter`にも除外エントリを足した。4env全てビルド成功
（`pio run -e <env>`）、既存`esp32dev`本線ビルドも壊れていないことを確認済み。

## なぜこの設計にしたか

- **配線・ライブラリの正確性を優先し、各ライブラリのヘッダ・exampleを実際に取得して
  API(`begin()`/`readData()`/`readMotionCount()`/`readBurst()`の引数・戻り値)を
  確認してから書いた。** 推測で書いた場合コンパイルは通っても実機で誤動作しかねない。
- `tedyapo/arduino-MLX90393`はタグ付けされていないリポジトリなので、他の外部依存と
  同じ「タグでpinする」原則([CLAUDE.md](../../CLAUDE.md)の不変条件)をコミットハッシュ
  (`4b044b532be969a4464e58fa488459d97248596d`、2026-08-27時点master)で代替した。
- PMW3901/PMW3360DMは同じSPIバス配線(SCK18/MISO19/MOSI23/CS5)を共有できるようにし、
  ブレッドボード配線をどちらのブリングアップでも使い回せるようにした（同時には焼かない
  ので競合しない）。

## まだやっていないこと

**実機に焼いて反応を見る机上確認そのものは未実施。** ビルドが通ることまでしか確認して
いない。次は各envを実機に焼き、SS49Eなら磁石の接近、PMW3901/PMW3360DMなら手近な模様
の上で動かす、MLX90393なら方向情報付きで磁石を動かす、といった手元での反応確認が必要。

その先の「質量-バネ系そのものの機械設計(f0を1-10Hz帯より下げ、制動比を臨界制動近くに
追い込む)」は[docs/other-sensors.md §3.1](../other-sensors.md)の通りまだ何も手を付けて
いない。今回のブリングアップはセンサ単体が生きているかの確認に過ぎない。
