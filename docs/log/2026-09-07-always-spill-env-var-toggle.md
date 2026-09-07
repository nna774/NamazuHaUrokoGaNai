# 実機トグルを専用envではなく環境変数に切り替えた

[log/2026-09-07-batch-spill-build-flag.md](2026-09-07-batch-spill-build-flag.md)で
常時spill化(PR #184)を`NAMZ_ALWAYS_SPILL`ビルドフラグ化し、実機で試す用に
`esp32dev-always-spill`・`adxl355-always-spill`・`piezo-always-spill`の3envを
`platformio.ini`に追加した。その直後、ユーザーから「この`-always-spill`のような
専用envパターンを続けると、今後トグルが増えるたびにenv数が掛け算で増えていく
のでは」と指摘があり、その通りだったため方式を変えた。

## 何が問題だったか

「base env × トグル」で専用envを1本ずつ足す設計は、トグルが1個のうちは
`esp32dev-always-spill`のように増分3つ（本番3系統ぶん）で済むが、2個目の
トグルが増えた時点で「両方有効」を試したい組み合わせまで専用envにすると
本番系統数×2^トグル数で指数的に増える。CIのマトリクスも同様に増える。

## 変更

- `firmware/flags_from_env.py`を新設。`extra_scripts`から読まれ、シェルの
  環境変数(例: `NAMZ_ALWAYS_SPILL`)が立っていればそのビルドフラグを
  `env.Append(BUILD_FLAGS=...)`で追加する。単体実行(`python firmware/flags_from_env.py`)
  すると、今どんなトグルが定義されていてどれが有効かを一覧できる。
- 新しいトグルを足す時はこのスクリプトの`TOGGLES`辞書に1行足すだけでよい。
  envは増えない。複数トグルを同時に試したい時も
  `NAMZ_ALWAYS_SPILL=1 NAMZ_FOO=1 pio run -e esp32dev`のように環境変数を
  並べるだけで組み合わせを作れる（専用envが要らない）。
- `esp32dev-always-spill`等の3envを`platformio.ini`から削除した。
- `firmware-build`CIのマトリクスを、`matrix.env`の直積ではなく`include`で
  明示的な組み合わせのリストに変えた（本番3系統の通常ビルド + 同じ3系統への
  `namz_always_spill: "1"`の6件、他は従来通り）。envを増やす方式なら
  トグルが増えるたびマトリクスも掛け算で増えたが、`include`方式なら
  「今CIで確認したい組み合わせ」を選んで足すだけなので線形にしか増えない。

## トレードオフ

専用env方式は`platformio.ini`を眺めるだけで「何が焼けるか」が分かり、
`pio run -e <Tab補完>`で発見できる。環境変数方式はini内には現れないので、
`python firmware/flags_from_env.py`で一覧できるようにして発見性を補った
（ユーザーからの追加指摘を受けて用意した）。CIのマトリクスに載せる組み合わせを
選ぶ手間自体は変わらず残るが、増え方が指数的から線形になる点が主な利得。
