"""実機で試す系の切り替えフラグ(NAMZ_ALWAYS_SPILL等)を、専用envを増やさず
環境変数で切り替える。

[env:xxx-always-spill]のような「base env × フラグ」の掛け算でplatformio.iniの
env数が増えるのを避けるため——フラグが複数並ぶと組み合わせが指数的に増える
（docs/log/2026-09-07-always-spill-env-var-toggle.md）。esp32dev/piezoの
extra_scriptsから読まれる（adxl355はesp32devをextendsしているので自動で継承）。

  NAMZ_ALWAYS_SPILL=1 pio run -e esp32dev -t upload --upload-port <USBポート>

どのフラグが切り替え可能かは単体実行で一覧できる:

  python firmware/flags_from_env.py

新しいトグルを足す時はTOGGLESに1行足すだけでよい。envは増えない。
"""

import os

TOGGLES = {
    "NAMZ_ALWAYS_SPILL": (
        "常時spill化。バッチのenqueue()直後にflushToSpill()を呼び、組み立て完了〜"
        "送信成功までRAM上にしか無い区間を無くす(docs/design.md「送信の信頼性」)。"
    ),
}


def _apply(env) -> None:
    for name in TOGGLES:
        if os.environ.get(name):
            env.Append(BUILD_FLAGS=[f"-D{name}=1"])


def _print_list() -> None:
    print("切り替え可能なビルドフラグ(環境変数で有効化。NAME=1 pio run -e <env> の形で使う):")
    for name, desc in TOGGLES.items():
        state = "有効" if os.environ.get(name) else "無効(既定)"
        print(f"  {name} [{state}]")
        print(f"    {desc}")


if __name__ == "__main__":
    _print_list()
else:
    Import("env")  # noqa: F821  (PlatformIOのSConstruct注入シンボル)
    _apply(env)
