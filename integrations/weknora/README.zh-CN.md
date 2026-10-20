# WeKnora 集成：用 PageSeam 做解析引擎

[English](README.md) | 简体中文

[WeKnora](https://github.com/Tencent/WeKnora) 内置的 PDF 解析器不做 OCR（扫描页要靠视觉模型），也不识别表格结构。`bridge.py` 把 PageSeam 接成 WeKnora 的解析引擎：扫描页走 PaddleOCR，表格保留结构，跨页表格合并成一张，页眉页脚和页码去掉。

**不改 WeKnora**：代码、镜像、配置都不动，用的是它自带的「MinerU 自建引擎」接口（v0.8.3 实测）。

```
上传文件 → WeKnora（知识库规则选了 mineru）
             → GET /v1/health 得到 404，选旧版协议 → POST /file_parse
               → parser-bridge（WeKnora 内部网络，不映射端口）→ PageSeam（提交任务、等完成、取 Markdown）
           ← Markdown + 按 <!-- page N --> 拆出的 content_list（WeKnora 用它生成原文位置）
WeKnora 照常分块 → 嵌入 → 建索引
```

| 文件 | 作用 |
| --- | --- |
| `bridge.py` | 转接服务，只用 Python 标准库；还响应 `/docs`（WeKnora 的连通性检测）和 `/health` |
| `docker-compose.override.yml` | 和 WeKnora 一起启动 parser-bridge，只接入 `WeKnora-network`，限 0.5 核 / 256M |
| `configure_parser_engine.py` | 把空间的 MinerU 地址设为 `http://parser-bridge:8080`（`PUT /tenants/kv/parser-engine-config`），已是该值则不改 |

## 部署

1. 部署 PageSeam（见[主 README](../../README.zh-CN.md#快速开始)），记下地址和 API Key。地址要能从 WeKnora 的容器访问，比如 `http://<宿主机内网 IP>:8000`。
2. 在 WeKnora 的部署目录：
   ```bash
   mkdir -p parser-bridge && cp <本仓库>/integrations/weknora/bridge.py parser-bridge/
   cp <本仓库>/integrations/weknora/docker-compose.override.yml .
   ```
3. WeKnora 的 `.env` 里加上：
   ```bash
   PAGESEAM_URL=http://<宿主机内网 IP>:8000
   PAGESEAM_API_KEY=<PageSeam 的 API Key>
   SSRF_WHITELIST=<原有值>,parser-bridge   # 否则 WeKnora 拒绝访问内网容器
   ```
4. 启动：`docker compose -f docker-compose.yml -f docker-compose.override.yml up -d`
5. 登记引擎：在 WeKnora 网页的解析引擎设置里把 MinerU 地址填成 `http://parser-bridge:8080`，或者运行
   ```bash
   WEKNORA_BASE=http://127.0.0.1:8080 WEKNORA_EMAIL=<管理员> WEKNORA_PASSWORD=<密码> \
     python3 configure_parser_engine.py
   ```

API Key 只在 parser-bridge 里，WeKnora 本身不需要知道。

## 在知识库里启用

登记 MinerU 地址只是多了一个可选引擎，**每个知识库自己选**，没选的照常用内置解析器：

- 网页：知识库设置 → 解析 → 为 pdf、docx、doc 选「MinerU」；
- API：建库或更新时在 `chunking_config.parser_engine_rules` 里写
  `[{"file_types": ["pdf", "docx", "doc"], "engine": "mineru"}]`。

关掉：把规则删掉（或改回 builtin）即可，已经入库的文档要重新解析才会换回。

## 对比测试

3 个生成的样例分别用内置解析器和 PageSeam 入库，混合检索 + 重排取前 5，只看原文切片：

| 题目（能力） | 内置解析器 | PageSeam |
| --- | --- | --- |
| 文字页跨页表格 | 第 1 名 | 第 1 名 |
| **扫描页**跨页表格 | 未命中：扫描页没有文字 | 第 1 名 |
| 续页无表头、跨 3 页的表格 | 第 3 名 | 第 1 名 |
| 倾斜扫描图片（转成 PDF 上传） | 未命中 | 第 1 名 |

- 切片：WeKnora 把 PageSeam 的表格切成多段时每段都重复表头；扫描页的 HTML 表格转成了 Markdown 表格。所有切片都带原文位置（页码）。
- 耗时：每个文件 21–41 秒（8 核 CPU，主要是 OCR）。WeKnora 等 MinerU 的上限默认 1000 秒，parser-bridge 自己最多等 950 秒（`BRIDGE_TIMEOUT`）。

## 限制

- **图片不能直接上传**：WeKnora 在上传阶段就要求配置视觉模型（「上传图片文件需要设置 VLM 模型」），还没到选解析引擎。先把图片转成单页 PDF 再上传即可走 PageSeam。
- **跨页表格的切片标为起始页**：PageSeam 合并跨页表格后不再知道每行原来在哪一页，整张表记在起始页。
- **Excel 不走 PageSeam**：PageSeam 不支持 Excel，xlsx/xls 继续用 WeKnora 内置解析器。
- **负载**：PageSeam 默认同时处理 2 个任务，队列满（429）时 parser-bridge 会等待重试。
- **WeKnora 重建后前端报「加载模型列表失败」**：和本集成无关。WeKnora 前端的 nginx 只在启动时解析后端地址，后端容器重建后要 `docker compose restart frontend`。

## 许可证

本目录以 [MIT](LICENSE) 发布。
