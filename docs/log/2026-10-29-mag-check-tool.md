# 2026-10-29 MLX90393の固定オフセット・ドリフトを見る`tools/mag_check.py`

方位センサ検討（issue #250の手法3）で、手元のMLX90393を使えるか確かめる道具。
既存の机上確認スケッチ`firmware/src/mlx90393_main.cpp`（`pio run -e mlx90393-bringup[-c3] -t upload`）が
出す`t_ms,status,x_uT,y_uT,z_uT,temp_C`を読み、(a)回した時の円/球の中心＝固定オフセット
（ハードアイアン）と半径、(b)静置時の中央値の時間変化(µT/時)を出す。`firmware`側は変更していない。

## 余りの個体は磁化済み

手元に余っているMLX90393は、[2026-08-27のログ](2026-08-27-sensor-pickup-bringup-firmware.md)で
**鉄ピンに磁石を2cmまで近づけて磁化させた、まさにその個体**（ピンが抜けなかったもの）。
その時の静置ベースラインは、磁石を近づける前が`x≈2.3,y≈14.7,z≈-49µT`(ノルム51µT=地磁気そのもの)、
磁化直後が`x≈-42,y≈-34,z≈-86µT`(ノルム約102µT)、数分後`x≈-48.9,y≈-38.4,z≈-76.8µT`(ノルム約99µT)。
固定オフセットは概算で70µT台に達し、水平地磁気(約30µT)を上回る。

2か月経った今回の実測を上と比べれば、**鉄ピンの残留磁化が自然に戻るか**を実データで確認できる。
基準値は上の数字。ノルムが51µTに近づいていれば減衰、約100µTのままなら固定。

## 見方

- 回す: 水平な机でセンサをゆっくり1〜2周。半径は水平地磁気(約30µT)、中心が固定オフセット。
  3軸とも40µT以上振れる回し方なら球フィットになり、半径は全磁力(約45〜50µT)に相当する。
- 置く: 動かさず数十分以上。中央値のトレンド(µT/時)が磁化の安定性。
- 「オフセット/半径」が0.3未満なら補正で十分、1.0を超えるなら固定の磁化が支配的で、
  ピンを切る・消磁・別個体を検討する（issue #250）。

テストは`tools/tests/test_mag_check.py`（合成データでフィット・網羅度・ドリフトを検証）。

## 追記: C3の配線をGPIO3/4に寄せられるようにした

GPIO5/6は3.3V・GND(基板の反対側の辺)から遠く配線が長くなるため、同じ辺にあるGPIO3/4で使えるようにした
（ESP32-C3のI2Cは任意のGPIOに割り当てられる。避けるのはストラップのGPIO2・BOOTのGPIO9）。
`mlx90393_main.cpp`のピン番号を`-DMLX90393_SDA_PIN`/`-DMLX90393_SCL_PIN`で上書きできるようにし、
`[env:mlx90393-bringup-c3-gpio34]`（SDA=GPIO3、SCL=GPIO4）を足した。既定(5/6)は変えていない。
この作業用Mac(arm64・Rosettaなし)では公式`espressif32@7.0.1`のままだとビルドできない
(`toolchain-riscv32-esp`(8.4.0+2021r2)がx86_64版のみで`Bad CPU type in executable`。xtensa側はarm64ネイティブ)。
そのため`[env:mlx90393-bringup-c3-gpio34]`だけは`platform`をpioarduino版(55.03.311、arm64ネイティブのC3 toolchain)に
明示pinした。`pio run -e mlx90393-bringup-c3-gpio34`はSUCCESS(Flash 33.1%)で、コンパイルコマンドに
`-DMLX90393_SDA_PIN=3 -DMLX90393_SCL_PIN=4`が入っていることも確認した。既存の`mlx90393-bringup-c3`は公式pinのまま。
実機への書き込み・動作(status=0x00)は未確認。

注意: pioarduino版でビルドすると、追跡対象の`firmware/certs/amazon_root_ca1.pem.piobkp`が消える
（`board_build.embed_txtfiles`の処理の副作用とみられる）。`git checkout -- firmware/certs/`で戻すこと。
