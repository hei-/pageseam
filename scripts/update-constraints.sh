#!/usr/bin/env bash
# ==============================================================================
# 🔒 更新 constraints.txt：不带版本锁定重新构建镜像，导出实际安装的全部 Python 包版本
#
# 用法: ./scripts/update-constraints.sh [docker build 参数...]
#   例如国内构建: ./scripts/update-constraints.sh --build-arg PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
# 改了 requirements.txt、或要升级间接依赖时运行；之后重新构建镜像并跑 ./scripts/run-tests.sh
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="pageseam:update-constraints"

docker build --build-arg CONSTRAINTS= -t "$IMAGE" "$@" "$ROOT_DIR"
{
    echo "# 镜像中全部 Python 包的版本锁定（含间接依赖），由 scripts/update-constraints.sh 生成，不要手工修改"
    echo "# 构建 CPU 版镜像时生效；pip、setuptools 版本在 Dockerfile 中单独指定"
    # 镜像里没有 pip（构建最后卸载），用标准库读取已安装的包
    docker run --rm --entrypoint python "$IMAGE" -c '
import importlib.metadata as m
skip = {"pip", "setuptools", "wheel"}
pkgs = {(d.metadata["Name"], d.version) for d in m.distributions() if d.metadata["Name"].lower() not in skip}
print("\n".join(f"{n}=={v}" for n, v in sorted(pkgs, key=lambda p: p[0].lower())))
' 
} > "$ROOT_DIR/constraints.txt.tmp"
mv "$ROOT_DIR/constraints.txt.tmp" "$ROOT_DIR/constraints.txt"
docker rmi "$IMAGE" >/dev/null
echo "✅ 已更新 constraints.txt（$(grep -vc '^#' "$ROOT_DIR/constraints.txt") 个包）"
