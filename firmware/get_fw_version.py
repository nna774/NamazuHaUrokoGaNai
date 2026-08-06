"""ビルド時にgitの短縮hashをNAMZ_FW_VERSIONへ、env名からNAMZ_OTA_ENVを注入する
(docs/ota.md §7)。

pull型OTAはビルドバージョンの一致判定でトリガーするので、焼いたバイナリが
「どのコミットか」を自己申告できないと成立しない。作業ツリーが汚れていたら
-dirtyを付け、未コミット状態を配布版として掴む事故に気付けるようにする。

NAMZ_OTA_ENVは「センサ・ボードの組」を表す（esp32dev/adxl355。espota用の
"-ota" envはアップロード方式が違うだけで中身は同じビルドなのでesp32dev/adxl355に
畳み込む）。platformio.ini側の各envに`-DNAMZ_OTA_ENV=...`を個別に書くと、
adxl355が`${env:esp32dev.build_flags}`ごと継承する際に二重定義警告が出るので、
ここでenv名から一元的に決める。
"""

import subprocess

Import("env")  # noqa: F821  (PlatformIOのSConstruct注入シンボル)


def _git_version() -> str:
    project_dir = env["PROJECT_DIR"]
    try:
        rev = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=project_dir, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"
    try:
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=project_dir, stderr=subprocess.DEVNULL
        ).decode().strip())
    except Exception:
        dirty = False
    return rev + ("-dirty" if dirty else "")


def _ota_env() -> str:
    pioenv = env["PIOENV"]
    return "adxl355" if pioenv.startswith("adxl355") else "esp32dev"


env.Append(BUILD_FLAGS=[
    f'-DNAMZ_FW_VERSION=\\"{_git_version()}\\"',
    f'-DNAMZ_OTA_ENV=\\"{_ota_env()}\\"',
])
