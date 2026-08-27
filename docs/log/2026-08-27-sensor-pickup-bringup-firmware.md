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

## 追記: phase0で使うマイコンがESP32-C3 SuperMini・ESP32-S3 miniと判明

ユーザーから、手持ちの実験用マイコンとしてESP32-C3とESP32-S3 miniがあると教わった。
[docs/other-sensors.md §6](../other-sensors.md#6-未決定事項着手前にユーザーが決めること)
で未決定事項としていた「phase0で使うマイコン」がこれで解決したので、C3側は
4本のブリングアップに`-c3`サフィックスのenvを追加した(`[env:hall-bringup-c3]`等)。

- **ピン配置は新規調査せず、既存の[docs/piezo.md §4](../piezo.md#4-ピン選定と最小配線phase0)
  のシルク印字確認結果をそのまま流用した**（同型のESP32-C3 SuperMini、GPIO2=ストラップ
  ピン・GPIO9=BOOTボタン専有を避けるという既知の制約も同じ）。
- SPIを使う2本(PMW3901/PMW3360DM)は、両ライブラリの`begin()`内部が引数無しの
  `SPI.begin()`を呼ぶだけと確認した上で、**先にカスタムピンで`SPI.begin(sck,miso,mosi,ss)`
  しておく**方式にした。ESP32のSPIClass::begin()は「既にバス開始済みなら何もせず
  returnする」実装(`arduino-esp32/libraries/SPI/src/SPI.cpp`で確認)なので、後から
  ライブラリが引数無しで呼んでも上書きされない。
- 4本ともC3向けビルドで成功を確認済み(`pio run -e hall-bringup-c3` 等)。
- **ESP32-S3 mini側は具体的な基板型番が未確認のため、まだピンを割り当てていない。**
  S3系はモデルによってオクタルPSRAM/フラッシュが特定GPIOを専有しており、それを
  他用途に配線すると起動不能になりうる（不可逆に壊しうるハードウェアリスク）ため、
  型番を確認してから対応する。

## 追記: SS49E用に使う実機のピン配置を写真で確認し、配線図を作った

SS49Eから試すことにしたユーザーに、実際に使うESP32-C3 SuperMini実機の写真(基板表面
シルク印字・裏面部品面の2枚)を見せてもらった。**この個体はdocs/piezo.mdのピエゾ機とは
シルク印字の並び順が異なる別個体**と判明:

- ピエゾ機(docs/piezo.md §4): 一辺が`5V,GND,3V3,RX,TX,GPIO2,GPIO1,GPIO0`、もう一辺が
  `GPIO10〜GPIO3`
- 今回の個体(HW-466AB): USB-C側の辺が`5V,GND,3.3,GPIO4,GPIO3,GPIO2,GPIO1,GPIO0`、
  反対側が`GPIO5〜GPIO10,GPIO20(RX),GPIO21(TX)`

**ただしGPIO番号自体の機能(ADC1がGPIO0-4のみ・GPIO2がストラップピン・GPIO9がBOOT
ボタン専有)はESP32-C3チップ自体の仕様であり、基板の印字順とは無関係。** そのため
`hall_main.cpp`の`kHallPin = 3`はこの個体でもそのまま正しく、コード変更は不要だった
——変わるのは「物理的にどのピンがどこにあるか」を示す配線図の方だけ。

`docs/img/ss49e-esp32c3-wiring.svg`にこの個体の実物配置での配線図を作成した
(VCC→3.3V、GND→GND、OUT→GPIO3、GPIO2/GPIO9は赤破線で「触るな」表示)。headless
Chromeでレンダリング確認済み(`docs/log/`ではなくスクラッチで確認、SVG自体は
リポジトリに残す)。

**教訓: 「ESP32-C3 SuperMini」という製品名が同じでも、個体・ロットによって
シルク印字の並び順が変わりうる。配線図は「実際に使う現物」の写真で確認してから
描くこと。** GPIO番号の機能はチップ仕様なので毎回不変だが、物理的な位置は毎回
確認が要る。

## 追記: SS49E本体の+/−/0記号をデータシートで同定した

SS49E本体には印字が無く、ユーザーが見ていたHoneywellのデータシート
(SS39ET/SS49E/SS59ET Series)には`+ - 0`という記号しか無くて分からない、との
相談を受けた。データシートPDFを取得し確認したところ:

- Figure 1 (Current Sourcing Output Block Diagram): `Vs(+)`・`OUTPUT(O)`・`V-(-)`
  の3端子と判明。「0」は数字のゼロではなく「OUTPUT」の意味の記号だった。
- Figure 4 (Mounting Dimensions、パッケージ図): 「SS49E」の実体図で、フラット面
  (N/S矢印が印字されている感磁面)を手前に、リードを下向きにして見た状態で
  **左から `+`(VCC)・`−`(GND)・`0`(OUTPUT)** の順とリード配置まで確定できた。

`docs/img/ss49e-esp32c3-wiring.svg`をこの実際の並びに合わせて描き直した
(モジュール側の並びを仮置きから確定情報に更新、パッケージの向き(フラット面を
手前に)も図中に明記)。headless Chromeで再レンダリングし、ラベルの重なりが
無いことも確認した。

## まだやっていないこと

**実機に焼いて反応を見る机上確認そのものは未実施。** ビルドが通ることまでしか確認して
いない。次は各envを実機に焼き、SS49Eなら磁石の接近、PMW3901/PMW3360DMなら手近な模様
の上で動かす、MLX90393なら方向情報付きで磁石を動かす、といった手元での反応確認が必要。

その先の「質量-バネ系そのものの機械設計(f0を1-10Hz帯より下げ、制動比を臨界制動近くに
追い込む)」は[docs/other-sensors.md §3.1](../other-sensors.md)の通りまだ何も手を付けて
いない。今回のブリングアップはセンサ単体が生きているかの確認に過ぎない。

ESP32-S3 miniの具体的な基板型番の確認も残っている。
