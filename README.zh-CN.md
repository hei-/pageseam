# PageSeam

**把 PDF、Word 和扫描件转成干净的 Markdown、可搜索 PDF 或 Word，CPU 就能跑，部署在你自己的服务器上。**

[English](README.md) | 简体中文

支持 PDF、Word（doc / docx）、PPT 和图片，Markdown 输出专为知识库和大模型设计。逐页自动判断是否需要 OCR：文字型页直接用原文，一个字都不会改；扫描页、乱码页和页内图片用 PaddleOCR 识别。**跨页的表格合并成一张表**。文件不出你的服务器。

- **扫描件**：逐页判断，只对需要的页 OCR；轻微倾斜自动转正，扫描表格逐格准确率 98.4%（见 [TESTING.md](TESTING.zh-CN.md#当前基线完整评测8-核-cpu)）。
- **表格**：保留合并单元格（HTML 表格）；跨页表格合并，重复表头去掉，被分页截断的行接回去。
- **给知识库用**：每页带 `<!-- page N -->` 标记，检索结果能引用页码；页眉、页脚、页码去掉，免得每页多出一个噪声分段。
- **接入**：REST API 和上传页面；[Dify 插件](dify-plugin/readme/README_zh_Hans.md)（工作流、知识流水线）；[WeKnora 解析引擎](integrations/weknora/README.zh-CN.md)。

| 输入 | 处理 |
|------|------|
| PDF | 逐页判断，见「自动判断」 |
| Word（doc、docx、rtf、odt、wps）、PPT（ppt、pptx、odp） | 先用 LibreOffice 转成 PDF，再走同一条流程：原生文字成为文字层，不 OCR；**嵌入的扫描页、截图会被识别** |
| 图片（png、jpg、tif、webp、bmp） | 整页 OCR，按原图分辨率识别（不放大）；多页 TIFF 每帧一页；手机照片按 EXIF 方向转正 |

Excel 不支持：转成 PDF 会按打印区域分页，表格结构被打散，按行读取的 Excel 解析器效果更好。

## 快速开始

需要 Docker，内存至少 8GB（默认 2 个任务进程，各约 2.8GB）。

```bash
echo "PAGESEAM_API_KEYS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env
docker compose up -d --build      # 首次构建约 15 分钟：镜像约 4.2GB，其中 OCR 模型约 600MB 在构建时预下载
```

上传页面 `http://localhost:8000/`（填入 `.env` 里的 API Key），接口文档 `/docs`。运行时不需要访问外网。

构建参数：

| 参数 | 说明 |
|------|------|
| `APT_MIRROR` | Debian 镜像源，国内可用 `mirrors.aliyun.com`、`mirrors.cloud.tencent.com` |
| `PIP_INDEX` | PyPI 镜像源，默认 `https://pypi.org/simple/`；国内可用 `https://mirrors.aliyun.com/pypi/simple/` |
| `PADDLE_PACKAGE`、`PADDLE_INDEX` | PaddlePaddle 版本和源，GPU 版见「GPU 部署」 |
| `CONSTRAINTS` | 版本锁定文件，默认 `constraints.txt`：全部 Python 包（含间接依赖）都锁定版本，每次构建结果一致。升级依赖时改 `requirements.txt`，再运行 `scripts/update-constraints.sh` |
| `OCR_LAYOUT_MODEL`、`OCR_DET_MODEL`、`OCR_REC_MODEL`、`OCR_TABLE_MODEL` | 构建时预下载的模型，要和运行时的同名环境变量一致 |

```bash
docker compose build --build-arg APT_MIRROR=mirrors.aliyun.com --build-arg PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
```

### Kubernetes

镜像可以直接用，注意：

- **只能 1 个副本**，更新策略用 `Recreate`：任务状态保存在进程内存中，更新时也避免两份模型同时占内存。
- `/data`（上传文件和结果）和 `/tmp` 用 `emptyDir`，配合 `readOnlyRootFilesystem: true`、`runAsNonRoot: true`（镜像用 UID 10001）。
- 内存 requests 3Gi、limits 7Gi（2 个任务进程）；存活和就绪探针用 `GET /health`。
- `API_KEYS` 从 Secret 注入。

## 配置

都通过环境变量设置（见 [`config.py`](docparser/config.py)）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `API_KEYS` | （必填） | 逗号分隔的多个 Key，便于轮换；每个 Key 只能看到自己提交的任务 |
| `MAX_WORKERS` | 2 | 同时处理的任务数。每个任务进程各加载一份模型，约 2.8GB |
| `OCR_THREADS` | 2 | 每个任务的 CPU 线程数 |
| `MAX_QUEUE` | 20 | 排队上限，超过返回 429 |
| `MAX_FILE_MB` / `MAX_PAGES` | 100 / 300 | 单个文件的大小和页数上限 |
| `JOB_TTL_MINUTES` | 60 | 结果保留时间，到期自动删除 |
| `OCR_DPI` | 200 | 扫描页渲染分辨率；小字号扫描件可调高 |
| `OCR_DESKEW` / `OCR_DESKEW_MAX` | 1 / 5 | 倾斜校正开关和最大角度 |
| `OCR_DEVICE` | cpu | `cpu`，或 `gpu` / `gpu:0`（需要 GPU 版镜像） |
| `OCR_*_MODEL` | 见上 | 模型组合，见「OCR 模型选择」 |
| `CLASSIFY_*` | 见「自动判断」 | 页面判定阈值 |
| `CONVERT_TIMEOUT` | 300 | LibreOffice 转换超时（秒） |
| `DEFAULT_LANGUAGE` | en | 请求没有 `Accept-Language` 时，报错、进度和判定报告用的语言（`en` / `zh`） |

## 输出

| 输出 | 说明 | 适合 |
|------|------|------|
| **可搜索 PDF** | 原页面一个像素都不改，在 OCR 识别出文字的位置叠加看不见的文字层 | 要求和原件一模一样，同时能选中、复制、搜索 |
| **Word** | 文字型页、混合页用 pdf2docx（保留原版式），OCR 页按版面块重新排版（标题、段落、表格、印章 / 图片），按原页序合并，每段一个分节，纸张大小和方向跟随原页。混合页中扫描的表格、文字截图默认换成可编辑内容（见下） | 需要编辑内容 |
| **Markdown** | 每页以 `<!-- page N -->` 开头；表格保留为 HTML（能表达合并单元格）；页眉、页脚、页码不输出（文字型页按各页重复出现的行判断，见下）；部首码位换回常用字 | 知识库、给 LLM 读 |

### 混合页中的图片（`word_images`）

文字页里插着扫描的表格、附件截图时，Word 中怎么处理这些图片：

| 取值 | 处理 |
|------|------|
| `replace`（默认） | 图片里识别出表格或文字（不少于 10 字）时，换成可编辑的 Word 表格和段落，放在原图位置；照片、Logo、示意图这类识别不出文字的图片保留 |
| `keep` | 全部保留为图片，外观与原件一致，图片里的文字不能编辑 |
| `both` | 保留图片，在图片下方附上识别出的表格和段落 |

实现方式：pdf2docx 转换前，在临时副本中挖掉有文字的图片，在原位置放一个占位标记；转换后把占位段落换成识别出的内容。正文部分仍然用原文，保留原版式。

## 跨页表格

Markdown 中，跨页的表格合并成一张表，放在起始页，前面加 `<!-- table pages 3-5 -->` 注明跨了哪几页（任务结果的 `summary.cross_page_tables` 也有记录）。

判断规则：第 N 页最后一块是表格（页码行不算），第 N+1 页第一块也是表格，并且：

- 列数相同（扫描件、没有设置重复标题行的 Word 表格），或者
- 第 N+1 页表格的第一行和表头相同（Word 的「重复标题行」、每页都印了表头的扫描件），合并时去掉重复的表头。

Word 表格默认「允许跨页断行」，一行里的长文字会被截成两半：续表第一行的第一列为空、列数和上一行相同时，把它接回上一页的最后一行。同一页内也有类似情况：单元格里自动换行的下半截被识别成单独一行（如 `|||M12||||`），第一列为空、一半以上单元格为空的行接回上一行。

合并后第 N+1 页只剩这张表时，继续检查第 N+2 页，所以一张表可以跨多页。文字型页的 Markdown 表格和扫描页的 HTML 表格也能合并（合并后输出 HTML）。

Dify 插件生成 `chunks` 时，跨页表格单独成段，标注「第 3–5 页」；超长的表格按行切开，每段都带表头。

> 不处理：表格中间插了文字说明（不再视为同一张表）；没有框线、只靠对齐排成的表格（文字型页识别不成表格）。第一列本来就为空的行会被当成截断的行接到上一行。

**Word 输出**默认和原件分页一致（`word_tables=keep`），每页一张表，方便逐页对照原件；判断失误时也不会把两张表拼在一起。需要编辑整张表（加行、排序、合计）时用 `word_tables=merge`：上一页最后一张表和下一页第一张表之间只有空段落、页码和分节符，并且列数相同或表头相同，就合并成一张表，去掉重复的表头，被截断的行接回去，表头设为「重复标题行」（Word 中跨页时自动重复）。两页纸张大小相同时，中间的分节符也一并去掉，表格随内容自动分页。可搜索 PDF 始终和原件一致。

## 自动判断

每页读取 4 项指标（只读 PDF 结构，毫秒级），按顺序匹配：

| 判定 | 条件 | 处理 |
|------|------|------|
| 扫描页 | 可见文字少于 20 字，图片覆盖超过 50% | 整页 OCR |
| 扫描页（带旧 OCR 层） | 同上，且有隐藏文字（渲染模式 3） | 删除旧文字层后重新 OCR（旧层质量未知，中文通常不如 PaddleOCR） |
| 文字已转曲线 | 没有文字，但有大量矢量路径 | 整页 OCR |
| 空白页 | 没有文字和图片 | 跳过 |
| 乱码页 | 有效字符比例低于 90%，或用了缺少 ToUnicode 映射的 Identity-H 字体 | 整页 OCR |
| 混合页 | 文字正常，但有单张图片超过页面 10% | 文字用原文，只对图片区域 OCR |
| 文字型页 | 以上都不是 | 不做 OCR |

每次转换返回逐页判定报告（判定、依据、耗时）。判断出错时可以用 `ocr=force`（全部 OCR）、`ocr=off`（不做 OCR），或 `ocr_pages=3,5-8` 指定页。阈值可以用环境变量 `CLASSIFY_<名称>` 调整（见 [`config.py`](docparser/config.py)）。

## 接口

除 `/health` 和上传页面外都需要 `Authorization: Bearer <API Key>`。每个 Key 只能看到自己提交的任务。报错信息、进度和逐页判定报告按 `Accept-Language` 返回中文或英文（如 `-H "Accept-Language: zh-CN"`），任务沿用提交时的语言。上传页面可以切换语言。

```bash
# 提交（异步，立即返回 job_id）
curl -H "Authorization: Bearer $KEY" -F file=@合同.pdf -F outputs=docx,pdf,markdown http://localhost:8000/v1/jobs
# 查询进度和逐页报告
curl -H "Authorization: Bearer $KEY" http://localhost:8000/v1/jobs/<job_id>
# 下载（kind: docx / pdf / markdown），用完可以删除；不删除的话 60 分钟后自动清理
curl -H "Authorization: Bearer $KEY" -OJ http://localhost:8000/v1/jobs/<job_id>/files/docx
curl -H "Authorization: Bearer $KEY" -X DELETE http://localhost:8000/v1/jobs/<job_id>
```

| 参数 | 说明 |
|------|------|
| `file` | PDF、Word（doc、docx、rtf、odt、wps）、PPT（ppt、pptx、odp）或图片（png、jpg、tif、webp、bmp）。图片每张一页（多页 TIFF 每帧一页）；Office 文件先转成 PDF，文件头和扩展名不符时返回 400 |
| `outputs` | 逗号分隔：`docx`、`pdf`、`markdown`，默认 `markdown` |
| `ocr` | `auto`（默认）/ `force` / `off` |
| `ocr_pages` | 额外指定整页 OCR 的页，如 `3,5-8` |
| `pages` | 只处理这些页，如 `1-10` |
| `word_images` | Word 中混合页的图片：`replace`（默认）/ `keep` / `both`，见上 |
| `word_tables` | Word 中的跨页表格：`keep`（默认）和原件分页一致 / `merge` 合并成一张表，见「跨页表格」 |

排队任务超过 `MAX_QUEUE` 时返回 429（带 `Retry-After`）。有打开密码的 PDF 返回 400。

## 性能与资源

测试环境 8 核 CPU、无 GPU（样例 10 页，其中 7 页需要 OCR）。模型选择表中的耗时为 4 线程：

| 指标 | 数值 |
|------|------|
| 文字型页 | 不到 1 秒 / 页 |
| OCR 页 | 约 5–8 秒 / 页（`OCR_THREADS=2`；4 线程时 3–6 秒） |
| 整份样例 | 40–60 秒（三种输出一起约 56 秒） |
| Word 转 PDF | 约 2–3 秒（3 页样例；LibreOffice 每次独立启动） |
| 内存 | 共约 5GB（2 个任务进程各加载一份模型） |

默认同时处理 2 个任务（`MAX_WORKERS=2`），每个任务 2 个 CPU 线程，容器限制 4 核 / 7GB（`docker-compose.yml`）。

## OCR 模型选择（实测）

| 配置 | 每页 | 内存 | 结果 |
|------|------|------|------|
| PP-StructureV3 默认（PP-DocLayout_plus-L + 服务端检测） | 42 秒 | 8GB | CPU 上不可用 |
| 全部轻量模型（PP-DocLayout-S + 移动端识别） | 3 秒 | 2GB | 丢正文，表格被当成图片 |
| **PP-DocLayout-M + 移动端检测 + 服务端识别 + SLANet_plus** | **3–6 秒** | **2.8GB** | **采用** |

文字型页的原文也做了几步清理（[`markdown.py`](docparser/markdown.py)）：

- **页眉页脚**：每页开头、结尾两块之内，在一半以上的页面重复出现的短文字去掉，页码不同也算（「内部资料 第 3 页」）。只统一页码形式的数字，「小计 300」这类正文不会误删；标题、表格不去掉。去掉的内容记在任务摘要的 `running_lines` 里。不去掉的话每页多一个只有页眉的分段，问题里出现手册名时会排到检索结果最前面。
- **部首码位**：有些 PDF 的字体把「车」「用」映射到康熙部首（U+2F00–2FD5）或部首补充（U+2E80–2EF3）里长得一样的字符，看起来正常，却检索不到。康熙部首用 NFKC 换回常用字，部首补充按对照表只换独立成字的。CJK 兼容表意文字（U+F900–FAFF，如「率」被映射成 U+F9DB）同理，用 NFC 换回。
- **合并单元格**：pymupdf4llm 生成的表格里，纵向合并的单元格只出现在第一行，后面的行是空的；文字垂直居中在两行之间时，连字符字形偏低会被分到下一行（「SP-200」变成「SP200」，「-15 ℃」丢了负号）；两行表头（「输出功率」下分「额定」「峰值」）被拆乱。有合并单元格的表格改为按 `find_tables` 的单元格结构（来自表格线）重新生成：文字按单词取，纵向合并的值填到它覆盖的每一行，多行表头拼成「输出功率/额定」，横向合并的数据单元格只在第一列保留。跨页续表里很高的单元格被 pymupdf4llm 按行距切成好几行时（行数和 `find_tables` 不一致），也这样重新生成。其余表格不动。

在 PP-StructureV3 之上补了几步处理（[`ocr.py`](docparser/ocr.py)）：

- **关闭表格方向分类**：它把宽而矮的表格误判为旋转过的表格，整张表被转置、行列倒序。
- **漏检区域兜底**：版面模型漏掉的区域，PP-StructureV3 会直接丢掉其中的文字。这些识别行按位置重新组成段落，插回阅读顺序。
- **倾斜校正**：OCR 前用投影法估算倾斜角（±5° 内，每页约 0.1–0.3 秒），转正后再识别，坐标换算回原图，可搜索 PDF 的文字层仍和原图对齐。扫描表格倾斜 0.6° 就会单元格错位。不用 PaddleOCR 自带的 UVDoc：CPU 上慢，非线性变形后坐标换算不回原图。`OCR_DESKEW=0` 关闭。
- **表格重新填格**：按单元格坐标重新分配识别行。相邻两格的文字被识别成一行时，按位置拆开容易切偏一两个字符，这些单行格子裁剪后单独识别；仍为空的格子也单独识别一次（单个数字、「—」容易被检测模型漏掉）。整格只有一笔横线的统一为「—」。
- **图片按原分辨率识别**：上传的图片按原图像素识别。pymupdf 默认按 96 DPI 定页面大小，再按 200 DPI 渲染会放大 2 倍多，表格模型在过大的图上会整张表错位。
- **页面方向**：横着、倒着扫描的页面先转正，坐标再换算回原页面；带 `/Rotate` 的页面按显示方向处理。
- **字号**：按「行宽 ÷ 字数」估算。识别框含外扩边距，用高度估算会偏大。
- **文本规范化**：数字中的全角逗号（`353，370.00`）改为半角；版面模型合在一起的列表项（`…。2.…`）拆开。

## 已知限制

- **Word 先转成 PDF 再解析**：版式按 LibreOffice 的排版，分页可能和 Word 略有不同；Word 里的宋体、黑体等字体用 Noto CJK 替代，不影响文字内容。docx 正文是中日韩文字、默认东亚语言却是 en-US（英文版 Word 模板、python-docx 生成的文件）时，转换前改成正文的语言：否则 LibreOffice 用西文字体渲染弯引号 “”，引号在文字层里成了单独的行，被挪到句末（「关键词车型。“ ”」）。原文件不改，只改转换用的副本。标题层级来自 PDF 书签（Word 的「标题 1/2/3」样式会导出成书签），没用标题样式的文档按字号判断。
- **LibreOffice 处理不可信文件**：转换时不运行宏；但文档里引用的外部链接图片可能被下载。只给内部用户使用时问题不大，对外开放前要限制容器的出网访问。

- **Word 中的 OCR 页会重新排版**：文字、表格、印章都在，但字体和行距和原件不同。要求和原件完全一致时使用可搜索 PDF。
- **混合页中换成可编辑内容的图片，版式按识别结果重新排**：图片原来占的高度不再保留，后面的内容会上移。要和原件一致时用 `word_images=keep`，或者使用可搜索 PDF。
- **OCR 有识别误差**：如样例中的「0.5‰」被识别成「0.5%。」、「X 轴」被识别成「×轴」。金额、账号等关键数字建议核对原件。扫描表格的单元格准确率见 [TESTING.md](TESTING.zh-CN.md#当前基线完整评测8-核-cpu)。
- **扫描表格的合并单元格**：跨多列的单元格（如「合计」行）结构可能识别错，同一张表的修复也会被跳过。
- **PPT**：演讲者备注不输出（LibreOffice 转 PDF 时不导出备注）；同一文本框中的多个项目符号可能被合成一行，文字不丢。
- **任务状态保存在内存中**：容器重启后未完成的任务丢失，客户端重新提交即可。所以只能单副本运行。
- **PaddlePaddle 固定为 3.2.2**：3.3.x 在 CPU（oneDNN）上运行 PP-StructureV3 时报 `ConvertPirAttribute2RuntimeAttribute not support`。

## GPU 部署

代码和镜像都支持 GPU，但还没有在 GPU 上实测。

```bash
docker build -t pageseam:gpu \
  --build-arg PADDLE_PACKAGE=paddlepaddle-gpu==3.2.2 \
  --build-arg PADDLE_INDEX=https://www.paddlepaddle.org.cn/packages/stable/cu126/ .
```

- **镜像**：CUDA 运行库随 pip 包安装，基础镜像不变。
- **运行**：`OCR_DEVICE=gpu:0`，容器要能使用 GPU（`docker run --gpus 1`，Kubernetes 申请 `nvidia.com/gpu: 1`）。
- **模型**：GPU 上可以换精度更高、在 CPU 上太慢的模型，例如版面 `PP-DocLayout_plus-L`、检测 `PP-OCRv5_server_det`。构建参数和运行环境变量用同一组，构建和运行使用的模型一致。
- **并发**：GPU 上可以适当增加 `MAX_WORKERS`。每个工作进程各加载一份模型，要按显存估算。

## 测试

测评流程、一键测试脚本和各层的通过标准见 [TESTING.zh-CN.md](TESTING.zh-CN.md)：

```bash
docker build -t pageseam .
./scripts/run-tests.sh                 # 单元测试 + 端到端检查 + 扫描表格逐格评测（快速）
./scripts/run-tests.sh tables --full   # 完整表格评测
```

测试在服务镜像里运行，只需要 Docker 和 python3。样例都是脚本生成的；生成的样例和自己的文件可以放在 `tests/samples/`（git 忽略），在上传页面人工验收。

## 文件结构

```
├── Dockerfile               # LibreOffice + 中文字体；构建时预下载 OCR 模型；CPU / GPU 版 PaddlePaddle 由构建参数决定
├── docker-compose.yml       # 单机部署
├── requirements.txt         # 直接依赖
├── constraints.txt          # 全部 Python 包的版本锁定
├── docparser/
│   ├── main.py              # FastAPI：鉴权、任务接口、上传页面
│   ├── jobs.py              # 任务队列：常驻工作进程（模型只加载一次）、进度、到期清理
│   ├── pipeline.py          # 一个任务的处理流程：（Office 转 PDF）→ 分类 → OCR → 三种输出
│   ├── convert.py           # LibreOffice：doc、docx、ppt 等转 PDF，检查文件头；图片转 PDF
│   ├── classify.py          # 逐页判断是否需要 OCR
│   ├── ocr.py               # PP-StructureV3 封装和补充处理（倾斜校正、表格重新填格）
│   ├── searchable_pdf.py    # 叠加隐藏文字层
│   ├── word.py              # pdf2docx + OCR 页排版 + 分节合并
│   ├── markdown.py          # Markdown 输出、跨页表格合并、按书签还原标题
│   └── static/index.html    # 上传页面
├── scripts/
│   ├── download_models.py
│   ├── update-constraints.sh  # 重新生成 constraints.txt
│   ├── security-check.sh    # 密钥、依赖漏洞、代码、Dockerfile、镜像漏洞检查
│   └── run-tests.sh         # 一键测试（在服务镜像中运行）
├── tests/                   # 单元测试、样例生成、端到端检查、表格逐格评测
├── dify-plugin/             # Dify 插件（MIT）
├── integrations/weknora/    # WeKnora 解析引擎转接（MIT）
├── TESTING.md               # 测评指南（中文版 TESTING.zh-CN.md）
└── THIRD_PARTY_NOTICES.md   # 第三方组件许可证（中文版 THIRD_PARTY_NOTICES.zh-CN.md）
```

## 许可证

[AGPL-3.0](LICENSE)。核心依赖 PyMuPDF 系列是 AGPL-3.0 / Artifex 商业许可双授权，所以本服务也用 AGPL：**通过网络向他人提供本服务（包括 SaaS）时，也要向这些用户提供完整源码，包括你的修改**。不想开放源码时，需要向 Artifex 购买 PyMuPDF 的商业许可。各依赖的许可证见 [THIRD_PARTY_NOTICES.zh-CN.md](THIRD_PARTY_NOTICES.zh-CN.md)。

`dify-plugin/` 和 `integrations/weknora/` 只通过 HTTP 调用服务，单独以 MIT 发布。
