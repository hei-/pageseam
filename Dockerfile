FROM python:3.11-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    DATA_DIR=/data \
    PADDLE_PDX_CACHE_HOME=/models \
    PADDLE_PDX_MODEL_SOURCE=BOS \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    HOME=/tmp

WORKDIR /app

# OpenCV 需要 libgl1 / libglib2.0-0，Paddle 需要 libgomp1
# LibreOffice（无界面版）把 doc、docx、ppt 等转成 PDF；Noto CJK 字体：Word 里的宋体、黑体等中文字体用它替代
# 国内构建可以换 APT 镜像源，例如 --build-arg APT_MIRROR=mirrors.aliyun.com
ARG APT_MIRROR=
# Debian 软件源只保留最新版，锁定 apt 包版本会让构建失败
# hadolint ignore=DL3008
RUN if [ -n "$APT_MIRROR" ]; then \
        echo "Using apt mirror: $APT_MIRROR" && \
        sed -i "s@deb.debian.org@$APT_MIRROR@g" /etc/apt/sources.list.d/debian.sources; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
        libreoffice-writer-nogui libreoffice-impress-nogui fonts-noto-cjk && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./

# PaddlePaddle 单独安装：默认 CPU 版；GPU 版用构建参数指定（见 README「GPU 部署」），例如
#   --build-arg PADDLE_PACKAGE=paddlepaddle-gpu==3.2.2 --build-arg PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu126/
# 3.3.x 在 CPU（oneDNN）上运行 PP-StructureV3 报 ConvertPirAttribute2RuntimeAttribute，固定 3.2.2
ARG PADDLE_PACKAGE=paddlepaddle==3.2.2
ARG PADDLE_INDEX=
# 国内构建可以换 PyPI 镜像源，例如 --build-arg PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
# --no-compile：不生成 .pyc，镜像小约 100MB
ARG PIP_INDEX=https://pypi.org/simple/
# constraints.txt 锁定全部 Python 包（含间接依赖）的版本，每次构建结果一致；
# 更新依赖用 scripts/update-constraints.sh，它以 --build-arg CONSTRAINTS= 不带锁定构建
ARG CONSTRAINTS=constraints.txt
# 先升级基础镜像自带的 pip（旧版本有已知安全漏洞）；装完依赖后：
# - setuptools 升到 83.0.0：基础镜像自带的版本里捆绑的 jaraco.context、wheel 有已知漏洞。
#   不能删除：PaddlePaddle 导入时会加载 setuptools 的 easy_install、bdist_egg
# - 卸载 pip：运行时用不到，它捆绑的 urllib3、msgpack 等有已知漏洞。需要时用 python -m ensurepip 装回
# PaddlePaddle 的版本写在构建参数 PADDLE_PACKAGE 的默认值里，hadolint 识别不出来
# hadolint ignore=DL3013
RUN echo "Using pip index: $PIP_INDEX" && \
    pip install --no-cache-dir --no-compile pip==26.2.1 -i "$PIP_INDEX" && \
    pip install --no-cache-dir --no-compile "$PADDLE_PACKAGE" ${CONSTRAINTS:+-c "$CONSTRAINTS"} -i "${PADDLE_INDEX:-$PIP_INDEX}" --extra-index-url "$PIP_INDEX" && \
    pip install --no-cache-dir --no-compile -r requirements.txt ${CONSTRAINTS:+-c "$CONSTRAINTS"} -i "$PIP_INDEX" && \
    pip install --no-cache-dir --no-compile setuptools==83.0.0 -i "$PIP_INDEX" && \
    pip uninstall -y pip

# 预下载 OCR 模型（约 600MB）。单独一层：只改代码时不需要重新下载
# 模型组合和 config.py 的默认值一致；GPU 部署换模型时用同名构建参数，构建和运行使用同一组模型
ARG OCR_LAYOUT_MODEL=PP-DocLayout-M
ARG OCR_DET_MODEL=PP-OCRv5_mobile_det
ARG OCR_REC_MODEL=PP-OCRv5_server_rec
ARG OCR_TABLE_MODEL=SLANet_plus
ENV OCR_LAYOUT_MODEL=$OCR_LAYOUT_MODEL OCR_DET_MODEL=$OCR_DET_MODEL OCR_REC_MODEL=$OCR_REC_MODEL OCR_TABLE_MODEL=$OCR_TABLE_MODEL
COPY docparser/__init__.py docparser/config.py docparser/ocr.py docparser/
COPY scripts/download_models.py scripts/
RUN python scripts/download_models.py && chmod -R a+rX /models

COPY docparser docparser

# 创建非 root 用户 (符合安全最佳实践)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -M appuser && \
    mkdir -p /data && chown appuser:appgroup /data

# 使用数字 UID，Kubernetes 的 runAsNonRoot 才能校验非 root
USER 10001

EXPOSE 8000

# 任务状态保存在进程内存中，只能用 1 个 uvicorn worker；并发由内部的任务进程池控制（MAX_WORKERS）
CMD ["sh", "-c", "uvicorn docparser.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log"]
