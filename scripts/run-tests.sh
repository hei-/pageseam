#!/usr/bin/env bash
# ==============================================================================
# 🧪 PageSeam 一键测试：用服务镜像（含依赖和 OCR 模型）跑测试，只需要 Docker 和 python3
#
# 用法: ./scripts/run-tests.sh [层级...] [--deployed] [--full]
#   层级（默认 unit e2e tables）:
#     unit    单元测试，约 1 分钟（跨页表格合并、页眉页脚、图片转 PDF、中英文文案、Dify 插件分段规则）
#     e2e     端到端检查，约 5 分钟（10 页混合样例、跨页表格和 Word 样例）
#     tables  扫描表格逐格评测，--quick 约 4 分钟；加 --full 测全部角度和 JPEG，约 15 分钟
#   --deployed  测试镜像中的代码；默认测试工作区的代码（复制进容器，镜像只提供依赖和模型）
#   --full      tables 层跑完整评测
#
# 镜像默认 pageseam:latest（先 docker build -t pageseam .），可用 PAGESEAM_IMAGE 指定。说明见 TESTING.md
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE="${PAGESEAM_IMAGE:-pageseam:latest}"

LEVELS=()
DEPLOYED=0
FULL=0
for arg in "$@"; do
    case "$arg" in
        unit|e2e|tables) LEVELS+=("$arg") ;;
        --deployed) DEPLOYED=1 ;;
        --full) FULL=1 ;;
        -h|--help) sed -n '3,14p' "$0"; exit 0 ;;
        *) echo "❌ 未知参数: $arg（可用: unit e2e tables --deployed --full）"; exit 1 ;;
    esac
done
[ ${#LEVELS[@]} -eq 0 ] && LEVELS=(unit e2e tables)

docker image inspect "$IMAGE" >/dev/null 2>&1 || {
    echo "❌ 找不到镜像 $IMAGE，先构建：docker build -t pageseam ."
    exit 1
}
echo "🎯 镜像: $IMAGE"
echo "📦 被测代码: $([ $DEPLOYED = 1 ] && echo '镜像中的代码' || echo '工作区')"

failed=()
run() {  # run <名称> <容器内命令>
    local name="$1" cmd="$2" start=$SECONDS cid rc
    echo ""
    echo "━━━ $name ━━━"
    cid="$(docker create -w /app "$IMAGE" sh -c "$cmd")"
    docker cp "$ROOT_DIR/tests" "$cid:/app/" >/dev/null
    [ $DEPLOYED = 0 ] && docker cp "$ROOT_DIR/docparser" "$cid:/app/" >/dev/null
    # 过滤 onnxruntime 和模型加载的日志噪声
    set +e
    docker start -a "$cid" 2>&1 \
        | grep --line-buffered -v -i -E 'onnxruntime|warn|Creating model|model files|^\[INFO\]|^\s*$'
    rc="$(docker wait "$cid")"
    set -e
    docker rm "$cid" >/dev/null
    if [ "$rc" = 0 ]; then
        echo "⏱  $((SECONDS - start)) 秒"
    else
        failed+=("$name")
        echo "❌ $name 失败（$((SECONDS - start)) 秒）"
    fi
}

for level in "${LEVELS[@]}"; do
    case "$level" in
        unit)
            run "导入检查：服务的所有模块" "python -c 'import docparser.main, docparser.pipeline; print(\"ok\")'"
            run "单元测试：跨页表格合并" "python tests/test_tables.py"
            run "单元测试：图片转 PDF" "python tests/test_images.py"
            run "单元测试：页眉页脚和部首码位" "python tests/test_text.py"
            run "单元测试：中英文文案" "python tests/test_i18n.py"
            echo ""
            echo "━━━ 单元测试：Dify 插件分段规则（不用容器，只依赖标准库）━━━"
            if (cd "$ROOT_DIR/dify-plugin" && python3 -B -m unittest discover tests 2>&1 | tail -3; exit "${PIPESTATUS[0]}"); then :; else failed+=("插件分段规则"); fi
            ;;
        e2e)
            run "端到端：10 页混合样例" "python tests/make_sample.py /tmp/sample.pdf >/dev/null && python tests/check_pipeline.py /tmp/sample.pdf /tmp/out"
            run "端到端：跨页表格和 Word" "python tests/make_tables_sample.py /tmp/s >/dev/null && python tests/check_tables.py /tmp/s /tmp/t"
            ;;
        tables)
            if [ $FULL = 1 ]; then
                run "扫描表格逐格评测（完整）" "python tests/eval_tables.py --min 0.8"
            else
                run "扫描表格逐格评测（快速）" "python tests/eval_tables.py --quick --min 0.8"
            fi
            ;;
    esac
done

echo ""
if [ ${#failed[@]} -eq 0 ]; then
    echo "✅ 全部通过"
else
    echo "❌ 未通过: ${failed[*]}"
    exit 1
fi
