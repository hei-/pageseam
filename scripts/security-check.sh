#!/usr/bin/env bash
# ==============================================================================
# 🛡️ 发布前安全检查：每个工具都用固定版本的官方 Docker 镜像运行，本机只需要 Docker
#
# 用法: ./scripts/security-check.sh [--image 镜像名]
#   默认检查（约 1–2 分钟）:
#     secrets       gitleaks 扫描仓库文件中的密钥
#     dependencies  pip-audit 按 constraints.txt 查 Python 依赖的已知漏洞（全部锁定版本，不用构建镜像）
#     code          bandit 查代码安全隐患（中、高风险算失败）
#     dockerfile    hadolint 检查 Dockerfile
#   --image 镜像名  另外用 Trivy 扫描构建好的镜像（系统软件包、LibreOffice），先 docker build -t pageseam .
#
# 环境变量:
#   REGISTRY_MIRROR  Docker Hub 镜像加速地址，如 mirror.example.com（拉取 docker.io 镜像时加在前面）
#   PIP_INDEX        安装 pip-audit、bandit 用的 PyPI 源，默认 https://pypi.org/simple/
#
# 已确认可以接受的结果在代码中就地注明（# nosec、# hadolint ignore），并写明原因
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRIVY_IMAGE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --image) TRIVY_IMAGE="${2:?--image 需要镜像名}"; shift 2 ;;
        -h|--help) sed -n '3,18p' "$0"; exit 0 ;;
        *) echo "❌ 未知参数: $1"; exit 1 ;;
    esac
done

PREFIX="${REGISTRY_MIRROR:+${REGISTRY_MIRROR%/}/}"
PIP_INDEX="${PIP_INDEX:-https://pypi.org/simple/}"
GITLEAKS="${PREFIX}zricethezav/gitleaks:v8.21.2"
HADOLINT="${PREFIX}hadolint/hadolint:v2.12.0-alpine"
TRIVY="${PREFIX}aquasec/trivy:0.75.0"
PYTHON="${PREFIX}library/python:3.11-slim"

# 代码用 docker cp 传进容器（不挂载本机目录），DOCKER_HOST 指向远程机器时也能用
failed=()
check() {  # check <名称> <镜像> <容器内命令> [docker run 额外参数...]
    local name="$1" image="$2" cmd="$3" cid rc
    shift 3
    echo ""
    echo "━━━ $name ━━━"
    cid="$(docker create "$@" -w /src --entrypoint sh "$image" -c "$cmd")"
    docker cp "$ROOT_DIR/." "$cid:/src" >/dev/null
    set +e
    docker start -a "$cid"
    rc="$(docker wait "$cid")"
    set -e
    docker rm "$cid" >/dev/null
    [ "$rc" = 0 ] && echo "✅ $name 通过" || { failed+=("$name"); echo "❌ $name 未通过"; }
}

check "密钥（gitleaks）" "$GITLEAKS" \
    "gitleaks dir /src --redact --no-banner --exit-code 1 2>&1"

check "依赖漏洞（pip-audit）" "$PYTHON" \
    "pip install -q --disable-pip-version-check --root-user-action=ignore -i '$PIP_INDEX' pip-audit==2.9.0 >/dev/null \
     && pip-audit -r constraints.txt --no-deps --disable-pip --vulnerability-service osv --progress-spinner off"

check "代码（bandit）" "$PYTHON" \
    "pip install -q --disable-pip-version-check --root-user-action=ignore -i '$PIP_INDEX' bandit==1.8.6 >/dev/null \
     && bandit -q -r docparser integrations dify-plugin scripts -ll"

check "Dockerfile（hadolint）" "$HADOLINT" \
    "hadolint --failure-threshold warning Dockerfile"

if [ -n "$TRIVY_IMAGE" ]; then
    echo ""
    echo "━━━ 镜像漏洞（Trivy：$TRIVY_IMAGE）━━━"
    if docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$TRIVY" image \
        --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$TRIVY_IMAGE"; then
        echo "✅ 镜像漏洞通过"
    else
        failed+=("镜像漏洞"); echo "❌ 镜像漏洞未通过"
    fi
fi

echo ""
if [ ${#failed[@]} -eq 0 ]; then
    echo "✅ 安全检查全部通过"
else
    echo "❌ 未通过: ${failed[*]}"
    exit 1
fi
